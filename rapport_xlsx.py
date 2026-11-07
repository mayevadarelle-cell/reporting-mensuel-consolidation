"""Rapport Excel du reporting mensuel : synthèse et graphique, compte de résultat, filiales, intragroupe, contrôles."""
import csv
from typing import Dict, List, Sequence, Tuple

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill

from commentaire import Commentaire, libelle_mois, valeurs_du_mois
from consolidation import (CHARGES, POSTES, PRODUITS, EcartIntra, Ecriture, budget_consolide, cumul, ecart_budget, kpis,
                           resultat_net, totaux_externes)

ENTETE = PatternFill("solid", fgColor="2F5D8A")
OK = PatternFill("solid", fgColor="D9EAD3")
ALERTE = PatternFill("solid", fgColor="F4CCCC")
EUROS = '#,##0.00 "€";[Red]-#,##0.00 "€"'
POURCENT = '0.0%;[Red]-0.0%'


def euros(centimes: int) -> float:
    return centimes / 100


def entete(feuille, ligne: int, textes: Sequence[str]) -> None:
    for colonne, texte in enumerate(textes, 1):
        c = feuille.cell(row=ligne, column=colonne, value=texte)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = ENTETE
        c.alignment = Alignment(wrap_text=True, vertical="center")


def largeurs(feuille, valeurs: Sequence[int]) -> None:
    for i, v in enumerate(valeurs):
        feuille.column_dimensions[chr(65 + i)].width = v


def ecrire_rapport(chemin: str, mois_rapport: str, mois: Sequence[str], ecritures: Sequence[Ecriture],
                   consolide: Dict[Tuple[str, str], int], budget: Dict[Tuple[str, str, str], int],
                   ecarts_intra: Sequence[EcartIntra], controles: Sequence[Tuple[str, bool, str]],
                   commentaire: Commentaire) -> None:
    classeur = Workbook()
    bud = budget_consolide(budget)

    # 1. Synthèse : indicateurs par mois et graphique
    synthese = classeur.active
    synthese.title = "Synthèse"
    synthese["A1"] = f"Reporting mensuel consolidé : {libelle_mois(mois_rapport)} (données fictives, Groupe Démo)"
    synthese["A1"].font = Font(bold=True, size=13)
    entete(synthese, 3, ["Mois", "CA réel", "CA budget", "Écart CA", "Marge brute", "EBITDA", "Résultat avant impôt", "Résultat budget"])
    for i, m in enumerate(mois):
        reel = valeurs_du_mois(consolide, m)
        b = valeurs_du_mois(bud, m)
        k = kpis(reel)
        res_bud = sum(b.get(p, 0) for p in PRODUITS) - sum(b.get(p, 0) for p in CHARGES)
        ligne = 4 + i
        valeurs = [m, euros(k["CA"]), euros(b.get("CA", 0)), None, euros(k["Marge brute"]), euros(k["EBITDA"]),
                   euros(k["Résultat avant impôt"]), euros(res_bud)]
        for col, v in enumerate(valeurs, 1):
            synthese.cell(row=ligne, column=col, value=v)
        synthese.cell(row=ligne, column=4, value=f"=B{ligne}-C{ligne}")
        for col in range(2, 9):
            synthese.cell(row=ligne, column=col).number_format = EUROS
    derniere = 3 + len(mois)
    largeurs(synthese, [12, 16, 16, 16, 16, 16, 20, 18])
    graphique = LineChart()
    graphique.title = "Chiffre d'affaires : réel et budget"
    graphique.height, graphique.width = 8, 16
    graphique.add_data(Reference(synthese, min_col=2, max_col=3, min_row=3, max_row=derniere), titles_from_data=True)
    graphique.set_categories(Reference(synthese, min_col=1, min_row=4, max_row=derniere))
    synthese.add_chart(graphique, f"A{derniere + 3}")

    # 2. Compte de résultat consolidé du mois, avec cumul
    cr = classeur.create_sheet("Compte de résultat")
    cr["A1"] = f"Compte de résultat consolidé : {libelle_mois(mois_rapport)} et cumul depuis janvier"
    cr["A1"].font = Font(bold=True, size=12)
    entete(cr, 3, ["Poste", "Réel mois", "Budget mois", "Écart (favorable > 0)", "Écart %", "Réel cumul", "Budget cumul", "Écart cumul"])
    reel = valeurs_du_mois(consolide, mois_rapport)
    b = valeurs_du_mois(bud, mois_rapport)
    cum_r = cumul(consolide, mois, mois_rapport)
    cum_b = cumul(bud, mois, mois_rapport)
    ligne = 4
    for poste in PRODUITS + CHARGES:
        e, p, _ = ecart_budget(poste, reel.get(poste, 0), b.get(poste, 0))
        ec, _, _ = ecart_budget(poste, cum_r.get(poste, 0), cum_b.get(poste, 0))
        for col, v in enumerate([POSTES[poste], euros(reel.get(poste, 0)), euros(b.get(poste, 0)), euros(e), p,
                                 euros(cum_r.get(poste, 0)), euros(cum_b.get(poste, 0)), euros(ec)], 1):
            cr.cell(row=ligne, column=col, value=v)
        ligne += 1
    cr.cell(row=ligne, column=1, value="Écart intragroupe non éliminé")
    cr.cell(row=ligne, column=2, value=euros(reel.get("ECART_INTRA", 0)))
    cr.cell(row=ligne, column=6, value=euros(cum_r.get("ECART_INTRA", 0)))
    ligne += 1
    res_cumul_budget = sum(cum_b.get(p, 0) for p in PRODUITS) - sum(cum_b.get(p, 0) for p in CHARGES)
    for col, v in enumerate(["RÉSULTAT AVANT IMPÔT", euros(resultat_net(reel)),
                             euros(sum(b.get(p, 0) for p in PRODUITS) - sum(b.get(p, 0) for p in CHARGES)), None, None,
                             euros(resultat_net(cum_r)), euros(res_cumul_budget), None], 1):
        c = cr.cell(row=ligne, column=col, value=v)
        c.font = Font(bold=True)
    for rangee in cr.iter_rows(min_row=4, max_row=ligne):
        for col in (1, 2, 3, 5, 6, 7):
            rangee[col].number_format = EUROS
        rangee[4].number_format = POURCENT
    largeurs(cr, [34, 16, 16, 20, 10, 16, 16, 16])

    # 3. Par filiale
    fil = classeur.create_sheet("Par filiale")
    fil["A1"] = f"Chiffre d'affaires et résultat par filiale, opérations intragroupe incluses : {libelle_mois(mois_rapport)}"
    fil["A1"].font = Font(bold=True, size=12)
    entete(fil, 3, ["Filiale", "CA externe", "Ventes intragroupe", "Charges", "Achats intragroupe", "Résultat avant impôt"])
    lignes_mois = [e for e in ecritures if e.mois == mois_rapport]
    for i, f in enumerate(sorted({e.filiale for e in lignes_mois})):
        sel = [e for e in lignes_mois if e.filiale == f]
        ca = sum(e.montant for e in sel if e.poste in PRODUITS)
        vi = sum(e.montant for e in sel if e.poste == "INTRA_PRODUIT")
        ch = sum(e.montant for e in sel if e.poste in CHARGES)
        ai = sum(e.montant for e in sel if e.poste == "INTRA_CHARGE")
        for col, v in enumerate([f, euros(ca), euros(vi), euros(ch), euros(ai), euros(ca + vi - ch - ai)], 1):
            c = fil.cell(row=4 + i, column=col, value=v)
            if col > 1:
                c.number_format = EUROS
    largeurs(fil, [14, 16, 20, 16, 20, 22])

    # 4. Intragroupe
    intra = classeur.create_sheet("Intragroupe")
    entete(intra, 1, ["Mois", "Vendeur", "Acheteur", "Montant vendeur", "Montant acheteur", "Écart", "Statut"])
    for i, e in enumerate(ecarts_intra):
        for col, v in enumerate([e.mois, e.vendeur, e.acheteur, euros(e.montant_vendeur), euros(e.montant_acheteur), euros(e.ecart), e.statut], 1):
            c = intra.cell(row=2 + i, column=col, value=v)
            if col in (4, 5, 6):
                c.number_format = EUROS
            if col == 7 and v == "à analyser":
                c.fill = ALERTE
    largeurs(intra, [10, 12, 12, 18, 18, 14, 14])

    # 5. Commentaire et contrôles
    com = classeur.create_sheet("Commentaire")
    com["A1"] = f"Commentaire : {libelle_mois(mois_rapport)}"
    com["A1"].font = Font(bold=True, size=12)
    com["A3"] = commentaire.texte or "(désactivé)"
    com["A3"].alignment = Alignment(wrap_text=True, vertical="top")
    com.row_dimensions[3].height = 150
    com["A5"] = f"Source : {commentaire.source}. À relire avant diffusion."
    for i, alerte in enumerate(commentaire.alertes):
        com.cell(row=6 + i, column=1, value=alerte)
    largeurs(com, [120])

    ctl = classeur.create_sheet("Contrôles")
    entete(ctl, 1, ["Contrôle", "Résultat", "Détail"])
    for i, (libelle, ok, detail) in enumerate(controles):
        for col, v in enumerate([libelle, "OK" if ok else "À TRAITER", detail], 1):
            c = ctl.cell(row=2 + i, column=col, value=v)
            if col == 2:
                c.fill = OK if ok else ALERTE
    largeurs(ctl, [58, 14, 60])
    classeur.save(chemin)


def exporter_csv_long(chemin: str, ecritures: Sequence[Ecriture], budget: Dict[Tuple[str, str, str], int]) -> None:
    """Fichier à plat (mois, filiale, poste, réel, budget) à importer dans Power BI ou Tableau."""
    reel = totaux_externes(ecritures)
    cles = sorted(set(reel) | set(budget))
    with open(chemin, "w", newline="", encoding="utf-8") as fichier:
        w = csv.writer(fichier)
        w.writerow(["mois", "filiale", "poste", "libelle_poste", "reel", "budget"])
        for f, m, p in ((f, m, p) for f, m, p in cles):
            w.writerow([m, f, p, POSTES.get(p, p), f"{reel.get((f, m, p), 0) / 100:.2f}", f"{budget.get((f, m, p), 0) / 100:.2f}"])
