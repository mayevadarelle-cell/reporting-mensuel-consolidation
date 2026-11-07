# Reporting mensuel consolidé et automatisé

Projet personnel de Darelle SIDJE (finance d'entreprise, contrôle de gestion, comptabilité des filiales).
**Toutes les données sont fictives** : le « Groupe Démo » et ses trois filiales sont inventés, la graine aléatoire est fixe. Le projet démontre une méthode, pas des résultats réels.

## Problème
Chaque mois, les filiales d'un groupe envoient leurs comptes de résultat, chacune dans son format, avec son plan de comptes. Le contrôle de gestion doit les rattacher à un plan commun, éliminer les opérations entre filiales, comparer au budget, contrôler, puis commenter. Faite à la main dans Excel, cette chaîne est longue et expose aux erreurs.

## Ce que fait la chaîne
1. **Lecture de trois formats différents** : séparateur, en-têtes, virgule ou point décimal, et surtout sens des signes (débit et crédit séparés, produits positifs et charges négatives, ou solde débit moins crédit). Tout est ramené à une convention unique, en centimes entiers (pas de flottants).
2. **Rattachement au plan du groupe** (`data/mapping_comptes.csv`). Un compte absent du plan **arrête** le reporting avec un message clair : mieux vaut s'arrêter que publier un chiffre faux.
3. **Réconciliation et élimination des opérations intragroupe** : chaque vente d'une filiale à une autre est rapprochée de l'achat correspondant, mois par mois. Les montants concordants sont éliminés ; un écart reste visible dans le résultat et dans l'onglet *Intragroupe* (statut « à analyser », ou « arrondi » sous 1 €).
4. **Compte de résultat consolidé** : chiffre d'affaires, marge brute, EBITDA, résultat d'exploitation, résultat avant impôt, avec le cumul depuis janvier.
5. **Écart au budget**, avec le bon sens des écarts : une charge plus basse que prévu est favorable.
6. **Contrôles automatiques** : toutes les remontées sont présentes ; le résultat consolidé est égal à la somme des résultats des filiales (les éliminations sont neutres) ; les opérations intragroupe concordent.
7. **Rapport Excel** (synthèse avec graphique, compte de résultat, par filiale, intragroupe, commentaire, contrôles) et **fichier à plat** pour Power BI ou Tableau (`rapport/donnees_powerbi.csv`).
8. **Commentaire**, en trois modes :
   - `modele` (par défaut) : texte produit par des règles à partir des seuls chiffres calculés ;
   - `simule` : même texte, passé dans le contrôle de chiffres d'une réponse d'IA ;
   - `claude` : l'IA reçoit uniquement des chiffres déjà formatés ; **tout nombre qu'elle cite doit figurer dans ces chiffres**, sinon son texte est rejeté et on revient au texte à base de règles. L'IA ne calcule rien. Le texte reste une aide à la rédaction, à relire avant diffusion.

## Résultats sur le jeu de données fictif (juin 2025)
| Indicateur | Montant |
|---|---|
| Chiffre d'affaires consolidé | 1 071 688,60 € (+3,3 % par rapport au budget, soit +33,8 k€) |
| Marge brute | 689 847,64 € |
| EBITDA | 377 841,87 € |
| Résultat avant impôt | 330 487,04 € (budget : 305,2 k€) |
| Chiffre d'affaires cumulé depuis janvier | 5 945,4 k€ (+1,0 % par rapport au budget) |

Trois écarts intragroupe ont été injectés dans les données et la chaîne les retrouve : 1 200 € en mars et 8 500 € en mai (DEMO_FR vers DEMO_BE, facture pas encore enregistrée par l'acheteur), et −350 € en avril (DEMO_SV vers DEMO_FR). Les deux autres contrôles passent.

## Utiliser
```bash
pip install -r requirements.txt
python generate_data.py                       # remontées des filiales, plan de rattachement, budget
python consolidation.py                       # dernier mois disponible, commentaire à base de règles
python consolidation.py --mois 2025-05        # un autre mois
python consolidation.py --commentaire simule  # ou claude, ou off
python -m pytest tests/ -v
```
Résultats dans `rapport/` : `reporting_mensuel.xlsx` et `donnees_powerbi.csv`.

### Avec Claude pour de vrai
```bash
pip install anthropic
export ANTHROPIC_API_KEY=...                  # ta clé, jamais dans le dépôt
python consolidation.py --commentaire claude
```
Le modèle se règle avec `MODELE_CLAUDE`. **N'envoie jamais de vrais comptes à une API externe sans autorisation** de l'entreprise concernée. L'appel réel n'est pas exécuté par les tests (faux client).

## Contenu
| Fichier | Rôle |
|---|---|
| `generate_data.py` | Génère les remontées des trois filiales (trois formats), le plan de rattachement et le budget |
| `consolidation.py` | Lecture, normalisation, intragroupe, consolidation, écarts, contrôles, ligne de commande |
| `commentaire.py` | Commentaire à base de règles et variante IA avec contrôle des chiffres |
| `rapport_xlsx.py` | Rapport Excel et fichier à plat |
| `tests/test_consolidation.py` | 20 tests : formats et signes, plan, intragroupe, éliminations, budget, contrôles, commentaire, rapport |

## Limites
- Consolidation **simplifiée** : compte de résultat seulement, intégration globale, une seule devise, pas de bilan, pas de conversion de devises, pas d'intérêts minoritaires, de goodwill ni de retraitements IFRS.
- Les opérations intragroupe sont rapprochées au niveau du couple vendeur et acheteur et du mois, pas facture par facture.
- Budget externe uniquement (hors intragroupe), au niveau du poste et de la filiale.
- Données synthétiques : les formats et les écarts ont été conçus par l'auteure du projet.
