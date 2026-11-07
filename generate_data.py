#!/usr/bin/env python3
"""Génère les remontées mensuelles FICTIVES de trois filiales d'un groupe imaginaire (« Groupe Démo », janvier à juin 2025).

Aucune donnée réelle. Graine fixe : le résultat est reproductible.
Chaque filiale envoie son compte de résultat dans SON format (séparateur, en-têtes, signes, plan de comptes) :

  data/entrees/demo_fr/AAAA-MM.csv   ;  compte;libelle;debit;credit            (virgule décimale)
  data/entrees/demo_be/AAAA-MM.csv   ,  account,description,amount              (produits > 0, charges < 0)
  data/entrees/demo_sv/AAAA-MM.csv   ;  Compte;Intitulé;Solde                   (solde = débit - crédit)
  data/mapping_comptes.csv           : plan de comptes local -> postes du groupe
  data/budget.csv                    : budget externe par filiale, poste et mois

Cas injectés : opérations intragroupe (ventes d'une filiale à une autre) avec des écarts entre le vendeur et l'acheteur
(facture non encore comptabilisée, arrondi), pour tester la réconciliation et l'élimination.
"""
import csv
import os
import random
from typing import Dict, List, Tuple

HERE: str = os.path.dirname(os.path.abspath(__file__))
SEED: int = 2026
MOIS: List[str] = [f"2025-{m:02d}" for m in range(1, 7)]
SAISON_REEL: List[float] = [0.92, 0.95, 1.02, 1.05, 1.08, 1.10]
SAISON_BUDGET: List[float] = [0.95, 0.97, 1.00, 1.03, 1.05, 1.07]
BRUIT: float = 0.03

# (compte local, libellé, nature, poste groupe, partenaire intragroupe, montant mensuel de base, sensible à la saison)
Ligne = Tuple[str, str, str, str, str, int, bool]
PLANS: Dict[str, List[Ligne]] = {
    "DEMO_FR": [
        ("7010", "Ventes de produits finis", "produit", "CA", "", 520_000, True),
        ("7060", "Ventes intragroupe", "produit", "INTRA_PRODUIT", "DEMO_BE", 40_000, True),
        ("7080", "Prestations diverses", "produit", "AUTRES_PRODUITS", "", 12_000, False),
        ("6010", "Achats de matières", "charge", "ACHATS", "", 210_000, True),
        ("6110", "Services intragroupe", "charge", "INTRA_CHARGE", "DEMO_SV", 15_000, False),
        ("6410", "Salaires", "charge", "PERSONNEL", "", 95_000, False),
        ("6450", "Charges sociales", "charge", "PERSONNEL", "", 38_000, False),
        ("6130", "Loyers", "charge", "EXTERNES", "", 18_000, False),
        ("6260", "Frais postaux", "charge", "EXTERNES", "", 4_000, False),
        ("6811", "Dotations aux amortissements", "charge", "DOTATIONS", "", 22_000, False),
        ("6610", "Intérêts d'emprunts", "charge", "FINANCIER", "", 6_000, False),
    ],
    "DEMO_BE": [
        ("700000", "Sales of goods", "produit", "CA", "", 310_000, True),
        ("604000", "Intercompany purchases", "charge", "INTRA_CHARGE", "DEMO_FR", 40_000, True),
        ("600000", "Raw materials", "charge", "ACHATS", "", 105_000, True),
        ("620000", "Wages", "charge", "PERSONNEL", "", 52_000, False),
        ("621000", "Social security", "charge", "PERSONNEL", "", 21_000, False),
        ("613000", "Rent", "charge", "EXTERNES", "", 12_000, False),
        ("614000", "Office expenses", "charge", "EXTERNES", "", 5_000, False),
        ("630000", "Depreciation", "charge", "DOTATIONS", "", 11_000, False),
        ("650000", "Interest expense", "charge", "FINANCIER", "", 3_000, False),
    ],
    "DEMO_SV": [
        ("7050", "Prestations clients", "produit", "CA", "", 140_000, True),
        ("7061", "Prestations intragroupe", "produit", "INTRA_PRODUIT", "DEMO_FR", 15_000, False),
        ("6040", "Sous-traitance", "charge", "ACHATS", "", 38_000, True),
        ("6411", "Rémunérations", "charge", "PERSONNEL", "", 62_000, False),
        ("6130", "Loyer", "charge", "EXTERNES", "", 7_000, False),
        ("6280", "Divers", "charge", "EXTERNES", "", 6_000, False),
        ("6812", "Dotations aux amortissements", "charge", "DOTATIONS", "", 5_000, False),
    ],
}
# Écarts injectés sur les opérations intragroupe : (filiale acheteuse ou vendeuse, mois, compte) -> variation en euros
ECARTS: Dict[Tuple[str, str, str], int] = {
    ("DEMO_BE", "2025-03", "604000"): -1_200,   # l'acheteur a comptabilisé 1 200 € de moins que le vendeur
    ("DEMO_BE", "2025-05", "604000"): -8_500,   # facture du vendeur pas encore enregistrée par l'acheteur
    ("DEMO_FR", "2025-04", "6110"): 350,        # l'acheteur a comptabilisé 350 € de plus que le vendeur
}


def euros(valeur: float) -> str:
    return f"{valeur:.2f}"


def virgule(valeur: float) -> str:
    return f"{valeur:.2f}".replace(".", ",")


def montants(rng: random.Random) -> Dict[Tuple[str, str], float]:
    """Montant réel mensuel de chaque ligne, après saison et bruit. Les opérations intragroupe sont calculées une fois."""
    reel: Dict[Tuple[str, str], float] = {}
    for filiale, lignes in PLANS.items():
        for compte, _, _, poste, _, base, saison in lignes:
            for i, mois in enumerate(MOIS):
                facteur = SAISON_REEL[i] if saison else 1.0
                reel[(filiale, compte, mois)] = round(base * facteur * (1 + rng.uniform(-BRUIT, BRUIT)), 2)
    # le vendeur et l'acheteur déclarent d'abord le même montant, puis on injecte les écarts
    for i, mois in enumerate(MOIS):
        reel[("DEMO_BE", "604000", mois)] = reel[("DEMO_FR", "7060", mois)]
        reel[("DEMO_FR", "6110", mois)] = reel[("DEMO_SV", "7061", mois)]
    for (filiale, mois, compte), delta in ECARTS.items():
        reel[(filiale, compte, mois)] = round(reel[(filiale, compte, mois)] + delta, 2)
    return reel


def ecrire(chemin: str, delimiteur: str, entetes: List[str], lignes: List[List[str]]) -> None:
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", newline="", encoding="utf-8") as fichier:
        writer = csv.writer(fichier, delimiter=delimiteur)
        writer.writerow(entetes)
        writer.writerows(lignes)


def entrees(reel: Dict[Tuple[str, str], float]) -> None:
    for i, mois in enumerate(MOIS):
        fr, be, sv = [], [], []
        for compte, libelle, nature, *_ in PLANS["DEMO_FR"]:
            m = reel[("DEMO_FR", compte, mois)]
            fr.append([compte, libelle, "" if nature == "produit" else virgule(m), virgule(m) if nature == "produit" else ""])
        for compte, libelle, nature, *_ in PLANS["DEMO_BE"]:
            m = reel[("DEMO_BE", compte, mois)]
            be.append([compte, libelle, euros(m if nature == "produit" else -m)])
        for compte, libelle, nature, *_ in PLANS["DEMO_SV"]:
            m = reel[("DEMO_SV", compte, mois)]
            sv.append([compte, libelle, virgule(-m if nature == "produit" else m)])
        base = os.path.join(HERE, "data", "entrees")
        ecrire(os.path.join(base, "demo_fr", f"{mois}.csv"), ";", ["compte", "libelle", "debit", "credit"], fr)
        ecrire(os.path.join(base, "demo_be", f"{mois}.csv"), ",", ["account", "description", "amount"], be)
        ecrire(os.path.join(base, "demo_sv", f"{mois}.csv"), ";", ["Compte", "Intitulé", "Solde"], sv)


def mapping() -> None:
    lignes = [[f, c, lib, nat, poste, partenaire] for f, plan in PLANS.items() for c, lib, nat, poste, partenaire, *_ in plan]
    ecrire(os.path.join(HERE, "data", "mapping_comptes.csv"), ",",
           ["filiale", "compte", "libelle", "nature", "poste", "partenaire"], lignes)


def budget(rng: random.Random) -> None:
    lignes: List[List[str]] = []
    for filiale, plan in PLANS.items():
        cumul: Dict[Tuple[str, str], float] = {}
        for compte, _, _, poste, _, base, saison in plan:
            if poste.startswith("INTRA"):
                continue
            for i, mois in enumerate(MOIS):
                facteur = SAISON_BUDGET[i] if saison else 1.0
                cumul[(poste, mois)] = cumul.get((poste, mois), 0.0) + base * facteur
        for (poste, mois), valeur in sorted(cumul.items()):
            lignes.append([filiale, mois, poste, euros(round(valeur, 2))])
    ecrire(os.path.join(HERE, "data", "budget.csv"), ",", ["filiale", "mois", "poste", "montant"], lignes)


def main() -> None:
    rng = random.Random(SEED)
    entrees(montants(rng))
    mapping()
    budget(rng)
    print(f"Données écrites dans {os.path.join(HERE, 'data')} ({len(MOIS)} mois, {len(PLANS)} filiales)")


if __name__ == "__main__":
    main()
