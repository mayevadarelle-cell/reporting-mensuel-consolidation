"""Tests du reporting consolidé (données fictives).

Lancer depuis le dossier du projet : python -m pytest tests/ -v
"""
import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(HERE)
sys.path.insert(0, RACINE)

from commentaire import nombres, produire_commentaire, verifier_chiffres  # noqa: E402
from consolidation import (Compte, Ecriture, ErreurDonnees, LigneBrute, charger, consolider, controles, ecart_budget,  # noqa: E402
                           en_centimes, format_demo_be, format_demo_fr, format_demo_sv, kpis, lire_remontees, normaliser,
                           reconcilier_intragroupe, resultat_net)

MAPPING = {
    ("F1", "70"): Compte("F1", "70", "produit", "CA", ""),
    ("F1", "60"): Compte("F1", "60", "charge", "ACHATS", ""),
    ("F1", "7060"): Compte("F1", "7060", "produit", "INTRA_PRODUIT", "F2"),
    ("F2", "6040"): Compte("F2", "6040", "charge", "INTRA_CHARGE", "F1"),
}


def test_en_centimes_virgule_et_point():
    assert en_centimes("1 234,56") == 123456
    assert en_centimes("-0.10") == -10
    assert en_centimes("") == 0


def test_les_trois_formats_donnent_la_meme_convention():
    # même produit de 100 €, même charge de 40 €, vus par chacune des trois filiales
    fr = format_demo_fr([{"compte": "70", "libelle": "v", "debit": "", "credit": "100,00"},
                         {"compte": "60", "libelle": "a", "debit": "40,00", "credit": ""}])
    be = format_demo_be([{"account": "70", "description": "v", "amount": "100.00"},
                         {"account": "60", "description": "a", "amount": "-40.00"}])
    sv = format_demo_sv([{"Compte": "70", "Intitulé": "v", "Solde": "-100,00"},
                         {"Compte": "60", "Intitulé": "a", "Solde": "40,00"}])
    assert [m for _, _, m in fr] == [m for _, _, m in be] == [m for _, _, m in sv] == [-10000, 4000]


def test_normalisation_donne_des_montants_positifs():
    brutes = [LigneBrute("F1", "2025-01", "70", "v", -10000), LigneBrute("F1", "2025-01", "60", "a", 4000)]
    assert [e.montant for e in normaliser(brutes, MAPPING)] == [10000, 4000]


def test_compte_inconnu_arrete_le_reporting():
    with pytest.raises(ErreurDonnees, match="F1/99"):
        normaliser([LigneBrute("F1", "2025-01", "99", "?", 1)], MAPPING)


def ecritures(vente, achat):
    return [Ecriture("F1", "2025-01", "7060", "INTRA_PRODUIT", "F2", vente),
            Ecriture("F2", "2025-01", "6040", "INTRA_CHARGE", "F1", achat),
            Ecriture("F1", "2025-01", "70", "CA", "", 100000), Ecriture("F2", "2025-01", "60", "ACHATS", "", 30000)]


def test_intragroupe_concordant():
    ecart = reconcilier_intragroupe(ecritures(5000, 5000))[0]
    assert ecart.ecart == 0 and ecart.statut == "concordant"


def test_intragroupe_arrondi_et_a_analyser():
    assert reconcilier_intragroupe(ecritures(5000, 4950))[0].statut == "arrondi"
    assert reconcilier_intragroupe(ecritures(5000, 3000))[0].statut == "à analyser"


def test_vente_sans_contrepartie_est_detectee():
    ecart = reconcilier_intragroupe(ecritures(5000, 0)[:1] + ecritures(5000, 0)[2:])[0]
    assert ecart.montant_acheteur == 0 and ecart.statut == "à analyser"


def test_elimination_concordante_ne_change_pas_le_resultat():
    e = ecritures(5000, 5000)
    c = consolider(e)
    valeurs = {p: v for (_, p), v in c.items()}
    assert "INTRA_PRODUIT" not in valeurs and "INTRA_CHARGE" not in valeurs
    assert resultat_net(valeurs) == 100000 - 30000   # le résultat externe seul


def test_ecart_intragroupe_est_conserve_dans_le_resultat():
    valeurs = {p: v for (_, p), v in consolider(ecritures(5000, 3000)).items()}
    assert valeurs["ECART_INTRA"] == 2000
    assert resultat_net(valeurs) == 100000 - 30000 + 2000


def test_resultat_consolide_egal_somme_des_filiales_avec_ecart():
    e = ecritures(5000, 3000)
    ok = [c for c in controles(e, consolider(e), ["2025-01"], []) if c[0].startswith("Résultat consolidé")][0]
    assert ok[1] is True


def test_kpis():
    k = kpis({"CA": 1000, "ACHATS": 300, "PERSONNEL": 200, "EXTERNES": 100, "DOTATIONS": 50, "FINANCIER": 10, "AUTRES_PRODUITS": 20})
    assert k["Marge brute"] == 700 and k["EBITDA"] == 420 and k["Résultat d'exploitation"] == 370
    assert k["Résultat avant impôt"] == 1000 + 20 - 300 - 200 - 100 - 50 - 10


def test_ecart_budget_sens_des_charges():
    assert ecart_budget("CA", 110, 100) == (10, 0.1, "favorable")
    assert ecart_budget("PERSONNEL", 110, 100) == (-10, -0.1, "défavorable")   # charge plus haute que prévu
    assert ecart_budget("PERSONNEL", 90, 100)[2] == "favorable"
    assert ecart_budget("CA", 10, 0) == (10, None, "favorable")


def test_fichier_manquant_est_signale(tmp_path):
    lignes, manquants = lire_remontees(str(tmp_path), ["2025-01"])
    assert lignes == [] and len(manquants) == 3
    ctl = controles([], {}, ["2025-01"], manquants)[0]
    assert ctl[1] is False


def test_nombres_et_verification():
    assert nombres("1 071,7 k€ soit +3,3 %") == {"1071.7", "3.3"}
    chiffres = "CA : 1 071,7 k€ ; écart 33,8 k€ (+3,3 %)"
    assert verifier_chiffres("Le CA est de 1 071,7 k€, écart de 33,8 k€.", chiffres, "2025-06") == []
    assert verifier_chiffres("Le CA est de 1 071,7 k€, soit 98,5 k€ de plus.", chiffres, "2025-06") == ["98.5"]


def donnees_jeu():
    d = os.path.join(RACINE, "data")
    mois = [f"2025-{m:02d}" for m in range(1, 7)]
    e, manquants, budget = charger(d, mois)
    return mois, e, manquants, budget


def test_jeu_complet_controles_et_ecarts_attendus():
    mois, e, manquants, budget = donnees_jeu()
    assert manquants == []
    ecarts = {(x.mois, x.vendeur, x.acheteur): x.ecart for x in reconcilier_intragroupe(e) if x.statut == "à analyser"}
    assert ecarts == {("2025-03", "DEMO_FR", "DEMO_BE"): 120000, ("2025-05", "DEMO_FR", "DEMO_BE"): 850000,
                      ("2025-04", "DEMO_SV", "DEMO_FR"): -35000}
    ctl = {c[0]: c[1] for c in controles(e, consolider(e), mois, manquants)}
    assert ctl["Résultat consolidé = somme des résultats des filiales"] is True
    assert ctl["Opérations intragroupe concordantes"] is False   # les trois écarts injectés


def test_commentaire_modele_et_simule_contiennent_des_chiffres_verifies():
    mois, e, _, budget = donnees_jeu()
    for mode in ("modele", "simule"):
        c = produire_commentaire(mode, "2025-06", mois, consolider(e), budget, reconcilier_intragroupe(e))
        assert "juin 2025" in c.texte and c.alertes == []


def test_commentaire_off():
    mois, e, _, budget = donnees_jeu()
    assert produire_commentaire("off", "2025-06", mois, consolider(e), budget, reconcilier_intragroupe(e)).texte == ""


def faux_client(reponse):
    r = SimpleNamespace(content=[SimpleNamespace(type="text", text=reponse)])
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: r))


def test_claude_texte_avec_chiffre_invente_est_rejete():
    mois, e, _, budget = donnees_jeu()
    args = ("claude", "2025-06", mois, consolider(e), budget, reconcilier_intragroupe(e))
    rejete = produire_commentaire(*args, client=faux_client("Le chiffre d'affaires atteint 9 999,9 k€ ce mois."))
    assert "rejeté" in rejete.source and rejete.alertes and "9999.9" in rejete.alertes[0]
    assert "9 999,9" not in rejete.texte   # on retombe sur le texte fondé sur les chiffres calculés


def test_claude_texte_qui_reprend_les_chiffres_fournis_est_accepte():
    mois, e, _, budget = donnees_jeu()
    base = produire_commentaire("modele", "2025-06", mois, consolider(e), budget, reconcilier_intragroupe(e)).texte
    accepte = produire_commentaire("claude", "2025-06", mois, consolider(e), budget, reconcilier_intragroupe(e),
                                   client=faux_client("En juin 2025, le chiffre d'affaires consolidé s'élève à 1 071,7 k€, soit +3,3 % par rapport au budget."))
    assert accepte.source == "IA, chiffres vérifiés" and accepte.alertes == [] and base


def test_rapport_excel(tmp_path):
    from openpyxl import load_workbook
    from commentaire import Commentaire
    from rapport_xlsx import ecrire_rapport, exporter_csv_long
    mois, e, manquants, budget = donnees_jeu()
    c = consolider(e)
    chemin = str(tmp_path / "r.xlsx")
    ecrire_rapport(chemin, "2025-06", mois, e, c, budget, reconcilier_intragroupe(e), controles(e, c, mois, manquants), Commentaire("x", "test"))
    assert load_workbook(chemin).sheetnames == ["Synthèse", "Compte de résultat", "Par filiale", "Intragroupe", "Commentaire", "Contrôles"]
    plat = str(tmp_path / "plat.csv")
    exporter_csv_long(plat, e, budget)
    assert open(plat, encoding="utf-8").readline().strip() == "mois,filiale,poste,libelle_poste,reel,budget"
