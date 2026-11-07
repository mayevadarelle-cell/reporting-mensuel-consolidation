#!/usr/bin/env python3
"""Reporting mensuel automatisé : consolidation de trois filiales fictives, écarts au budget, intragroupe.

Chaîne : lecture des remontées (un format par filiale) -> normalisation -> rattachement au plan de comptes du groupe ->
réconciliation et élimination des opérations intragroupe -> compte de résultat consolidé -> écart au budget ->
contrôles -> rapport Excel et commentaire.

Convention : tous les montants du groupe sont positifs, une charge est une charge. Les montants sont en centimes (entiers).

Usage :
    python consolidation.py [--mois AAAA-MM] [--commentaire off|modele|simule|claude]
"""
import argparse
import csv
import os
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Sequence, Tuple

HERE: str = os.path.dirname(os.path.abspath(__file__))
POSTES: Dict[str, str] = {
    "CA": "Chiffre d'affaires", "AUTRES_PRODUITS": "Autres produits", "ACHATS": "Achats et sous-traitance",
    "PERSONNEL": "Charges de personnel", "EXTERNES": "Charges externes", "DOTATIONS": "Dotations aux amortissements",
    "FINANCIER": "Charges financières",
}
PRODUITS: Tuple[str, ...] = ("CA", "AUTRES_PRODUITS")
CHARGES: Tuple[str, ...] = ("ACHATS", "PERSONNEL", "EXTERNES", "DOTATIONS", "FINANCIER")
INTRA: Tuple[str, str] = ("INTRA_PRODUIT", "INTRA_CHARGE")
SEUIL_ECART_BUDGET: float = 0.05   # au-delà de 5 % d'écart au budget, un poste est signalé
TOLERANCE_INTRA: int = 100         # 1,00 € : en dessous, un écart intragroupe est un simple arrondi


class ErreurDonnees(Exception):
    """Données d'entrée inutilisables : le reporting s'arrête plutôt que de produire un chiffre faux."""


@dataclass(frozen=True)
class LigneBrute:
    filiale: str
    mois: str
    compte: str
    libelle: str
    montant: int          # montant brut lu dans le fichier, signé selon le format de la filiale, en centimes


@dataclass(frozen=True)
class Compte:
    filiale: str
    compte: str
    nature: str           # "produit" ou "charge"
    poste: str
    partenaire: str


@dataclass(frozen=True)
class Ecriture:
    filiale: str
    mois: str
    compte: str
    poste: str
    partenaire: str
    montant: int          # positif, en centimes


def en_centimes(texte: str) -> int:
    propre = texte.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if propre in ("", "-"):
        return 0
    return int((Decimal(propre) * 100).to_integral_value())


def lire_csv(chemin: str, delimiteur: str) -> List[Dict[str, str]]:
    with open(chemin, newline="", encoding="utf-8") as fichier:
        return list(csv.DictReader(fichier, delimiter=delimiteur))


def format_demo_fr(lignes: List[Dict[str, str]]) -> List[Tuple[str, str, int]]:
    """compte;libelle;debit;credit : montant brut = débit - crédit."""
    return [(r["compte"], r["libelle"], en_centimes(r["debit"]) - en_centimes(r["credit"])) for r in lignes]


def format_demo_be(lignes: List[Dict[str, str]]) -> List[Tuple[str, str, int]]:
    """account,description,amount : produits positifs, charges négatives. On ramène à « débit - crédit »."""
    return [(r["account"], r["description"], -en_centimes(r["amount"])) for r in lignes]


def format_demo_sv(lignes: List[Dict[str, str]]) -> List[Tuple[str, str, int]]:
    """Compte;Intitulé;Solde : solde = débit - crédit."""
    return [(r["Compte"], r["Intitulé"], en_centimes(r["Solde"])) for r in lignes]


FORMATS: Dict[str, Tuple[str, Callable[[List[Dict[str, str]]], List[Tuple[str, str, int]]]]] = {
    "DEMO_FR": (";", format_demo_fr),
    "DEMO_BE": (",", format_demo_be),
    "DEMO_SV": (";", format_demo_sv),
}


def lire_mapping(chemin: str) -> Dict[Tuple[str, str], Compte]:
    return {(r["filiale"], r["compte"]): Compte(r["filiale"], r["compte"], r["nature"], r["poste"], r["partenaire"])
            for r in lire_csv(chemin, ",")}


def lire_remontees(dossier: str, mois: Sequence[str]) -> Tuple[List[LigneBrute], List[Tuple[str, str]]]:
    """Lit tous les fichiers disponibles. Retourne aussi la liste des (filiale, mois) dont le fichier est absent."""
    lignes: List[LigneBrute] = []
    manquants: List[Tuple[str, str]] = []
    for filiale, (delimiteur, lecteur) in FORMATS.items():
        for m in mois:
            chemin = os.path.join(dossier, filiale.lower(), f"{m}.csv")
            if not os.path.isfile(chemin):
                manquants.append((filiale, m))
                continue
            for compte, libelle, brut in lecteur(lire_csv(chemin, delimiteur)):
                lignes.append(LigneBrute(filiale, m, compte, libelle, brut))
    return lignes, manquants


def normaliser(lignes: Sequence[LigneBrute], mapping: Dict[Tuple[str, str], Compte]) -> List[Ecriture]:
    """Rattache chaque ligne au plan du groupe et ramène le montant au sens positif (produit : crédit - débit)."""
    inconnus = sorted({(l.filiale, l.compte) for l in lignes if (l.filiale, l.compte) not in mapping})
    if inconnus:
        raise ErreurDonnees("Comptes absents du plan de rattachement : " + ", ".join(f"{f}/{c}" for f, c in inconnus))
    resultat: List[Ecriture] = []
    for l in lignes:
        c = mapping[(l.filiale, l.compte)]
        montant = -l.montant if c.nature == "produit" else l.montant
        resultat.append(Ecriture(l.filiale, l.mois, l.compte, c.poste, c.partenaire, montant))
    return resultat


@dataclass(frozen=True)
class EcartIntra:
    mois: str
    vendeur: str
    acheteur: str
    montant_vendeur: int
    montant_acheteur: int

    @property
    def ecart(self) -> int:
        return self.montant_vendeur - self.montant_acheteur

    @property
    def statut(self) -> str:
        if self.ecart == 0:
            return "concordant"
        return "arrondi" if abs(self.ecart) <= TOLERANCE_INTRA else "à analyser"


def reconcilier_intragroupe(ecritures: Sequence[Ecriture]) -> List[EcartIntra]:
    """Rapproche chaque vente intragroupe du côté acheteur correspondant, mois par mois."""
    ventes: Dict[Tuple[str, str, str], int] = defaultdict(int)
    achats: Dict[Tuple[str, str, str], int] = defaultdict(int)
    for e in ecritures:
        if e.poste == "INTRA_PRODUIT":
            ventes[(e.mois, e.filiale, e.partenaire)] += e.montant
        elif e.poste == "INTRA_CHARGE":
            achats[(e.mois, e.partenaire, e.filiale)] += e.montant   # le partenaire de l'acheteur est le vendeur
    cles = sorted(set(ventes) | set(achats))
    return [EcartIntra(m, v, a, ventes.get((m, v, a), 0), achats.get((m, v, a), 0)) for m, v, a in cles]


def totaux_externes(ecritures: Sequence[Ecriture]) -> Dict[Tuple[str, str, str], int]:
    """(filiale, mois, poste) -> montant, hors opérations intragroupe."""
    t: Dict[Tuple[str, str, str], int] = defaultdict(int)
    for e in ecritures:
        if e.poste not in INTRA:
            t[(e.filiale, e.mois, e.poste)] += e.montant
    return t


def consolider(ecritures: Sequence[Ecriture]) -> Dict[Tuple[str, str], int]:
    """(mois, poste) -> montant consolidé. Les opérations intragroupe concordantes sont éliminées des deux côtés ;
    la part non réconciliée est conservée dans le poste « ECART_INTRA » (signé : > 0 = produit non éliminé)."""
    t: Dict[Tuple[str, str], int] = defaultdict(int)
    for (_, mois, poste), montant in totaux_externes(ecritures).items():
        t[(mois, poste)] += montant
    for ecart in reconcilier_intragroupe(ecritures):
        t[(ecart.mois, "ECART_INTRA")] += ecart.ecart
    return dict(t)


def resultat_net(valeurs: Dict[str, int]) -> int:
    return (sum(valeurs.get(p, 0) for p in PRODUITS) - sum(valeurs.get(p, 0) for p in CHARGES) + valeurs.get("ECART_INTRA", 0))


def kpis(valeurs: Dict[str, int]) -> Dict[str, int]:
    ca = valeurs.get("CA", 0)
    marge_brute = ca - valeurs.get("ACHATS", 0)
    ebitda = marge_brute + valeurs.get("AUTRES_PRODUITS", 0) - valeurs.get("PERSONNEL", 0) - valeurs.get("EXTERNES", 0)
    resultat_exploitation = ebitda - valeurs.get("DOTATIONS", 0)
    return {"CA": ca, "Marge brute": marge_brute, "EBITDA": ebitda, "Résultat d'exploitation": resultat_exploitation,
            "Résultat avant impôt": resultat_net(valeurs)}


def lire_budget(chemin: str) -> Dict[Tuple[str, str, str], int]:
    return {(r["filiale"], r["mois"], r["poste"]): en_centimes(r["montant"]) for r in lire_csv(chemin, ",")}


def budget_consolide(budget: Dict[Tuple[str, str, str], int]) -> Dict[Tuple[str, str], int]:
    t: Dict[Tuple[str, str], int] = defaultdict(int)
    for (_, mois, poste), montant in budget.items():
        t[(mois, poste)] += montant
    return dict(t)


def ecart_budget(poste: str, reel: int, budget: int) -> Tuple[int, Optional[float], str]:
    """Écart (favorable > 0) , en % du budget, et sens : une charge plus basse que prévu est favorable."""
    ecart = reel - budget if poste in PRODUITS else budget - reel
    pct = ecart / budget if budget else None
    return ecart, pct, "favorable" if ecart >= 0 else "défavorable"


def cumul(donnees: Dict[Tuple[str, str], int], mois: Sequence[str], jusqu_a: str) -> Dict[str, int]:
    """Cumul depuis le premier mois jusqu'au mois demandé inclus : poste -> montant."""
    t: Dict[str, int] = defaultdict(int)
    for (m, poste), montant in donnees.items():
        if m in mois and m <= jusqu_a:
            t[poste] += montant
    return dict(t)


def controles(ecritures: Sequence[Ecriture], consolide: Dict[Tuple[str, str], int], mois: Sequence[str],
              manquants: Sequence[Tuple[str, str]]) -> List[Tuple[str, bool, str]]:
    """Liste de contrôles (libellé, réussi, détail). Un contrôle en échec doit être traité avant diffusion."""
    resultats: List[Tuple[str, bool, str]] = []
    resultats.append(("Toutes les remontées sont présentes", not manquants,
                      "aucun fichier manquant" if not manquants else ", ".join(f"{f} {m}" for f, m in manquants)))
    # Le résultat consolidé doit être égal à la somme des résultats des filiales (les éliminations sont neutres)
    ecart_total = 0
    for m in mois:
        somme_filiales = 0
        for f in {e.filiale for e in ecritures}:
            lignes = [e for e in ecritures if e.filiale == f and e.mois == m]
            produits = sum(e.montant for e in lignes if e.poste in PRODUITS + ("INTRA_PRODUIT",))
            charges = sum(e.montant for e in lignes if e.poste in CHARGES + ("INTRA_CHARGE",))
            somme_filiales += produits - charges
        valeurs = {p: v for (mm, p), v in consolide.items() if mm == m}
        ecart_total += abs(somme_filiales - resultat_net(valeurs))
    resultats.append(("Résultat consolidé = somme des résultats des filiales", ecart_total == 0,
                      "écart nul" if ecart_total == 0 else f"écart de {ecart_total / 100:,.2f} €"))
    a_analyser = [e for e in reconcilier_intragroupe(ecritures) if e.statut == "à analyser"]
    resultats.append(("Opérations intragroupe concordantes", not a_analyser,
                      "toutes concordantes" if not a_analyser else f"{len(a_analyser)} écart(s) à analyser"))
    return resultats


def formater(centimes: int, signe: bool = False) -> str:
    texte = f"{abs(centimes) / 100:,.2f}".replace(",", " ").replace(".", ",")
    prefixe = "-" if centimes < 0 else ("+" if signe and centimes > 0 else "")
    return f"{prefixe}{texte}"


def charger(dossier_donnees: str, mois: Sequence[str]) -> Tuple[List[Ecriture], List[Tuple[str, str]], Dict[Tuple[str, str, str], int]]:
    mapping = lire_mapping(os.path.join(dossier_donnees, "mapping_comptes.csv"))
    brutes, manquants = lire_remontees(os.path.join(dossier_donnees, "entrees"), mois)
    return normaliser(brutes, mapping), manquants, lire_budget(os.path.join(dossier_donnees, "budget.csv"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Reporting mensuel consolidé (données fictives).")
    ap.add_argument("--mois", default=None, help="mois de reporting AAAA-MM (par défaut : le dernier disponible)")
    ap.add_argument("--commentaire", choices=["off", "modele", "simule", "claude"], default="modele",
                    help="commentaire : modele (texte à partir des chiffres), simule ou claude (IA, chiffres vérifiés), off")
    ap.add_argument("--sortie", default=os.path.join(HERE, "rapport", "reporting_mensuel.xlsx"))
    args = ap.parse_args()

    tous_les_mois = [f"2025-{m:02d}" for m in range(1, 13)]
    donnees = os.path.join(HERE, "data")
    existants = [m for m in tous_les_mois if any(os.path.isfile(os.path.join(donnees, "entrees", f.lower(), f"{m}.csv")) for f in FORMATS)]
    if not existants:
        raise SystemExit("Aucune remontée dans data/entrees : lance d'abord python generate_data.py")
    mois_rapport = args.mois or existants[-1]
    mois = [m for m in existants if m <= mois_rapport]
    ecritures, manquants, budget = charger(donnees, mois)
    consolide = consolider(ecritures)
    checks = controles(ecritures, consolide, mois, manquants)

    from commentaire import produire_commentaire
    texte = produire_commentaire(args.commentaire, mois_rapport, mois, consolide, budget, reconcilier_intragroupe(ecritures))

    k = kpis({p: v for (m, p), v in consolide.items() if m == mois_rapport})
    print(f"Mois de reporting : {mois_rapport} ({len(mois)} mois chargés)")
    for nom, valeur in k.items():
        print(f"  {nom:<25} {formater(valeur):>16} €")
    for libelle, ok, detail in checks:
        print(f"  [{'OK' if ok else 'A TRAITER'}] {libelle} : {detail}")

    from rapport_xlsx import ecrire_rapport, exporter_csv_long
    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    ecrire_rapport(args.sortie, mois_rapport, mois, ecritures, consolide, budget, reconcilier_intragroupe(ecritures), checks, texte)
    plat = os.path.join(os.path.dirname(args.sortie), "donnees_powerbi.csv")
    exporter_csv_long(plat, ecritures, budget)
    print(f"Rapport écrit : {args.sortie}\nFichier à plat pour Power BI : {plat}")
    if texte.texte:
        print(f"\nCommentaire ({texte.source}) :\n{texte.texte}")
        for alerte in texte.alertes:
            print(f"  [alerte] {alerte}")


if __name__ == "__main__":
    main()
