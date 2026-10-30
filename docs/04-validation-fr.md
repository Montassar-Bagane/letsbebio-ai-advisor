# Validation du moteur de recommandation

## Méthode

Un protocole de validation a été mis en place pour évaluer la pertinence des
recommandations produites par le moteur. Vingt-deux profils clients réalistes
ont été définis, couvrant les quatre domaines du catalogue (visage, cheveux,
corps, compléments alimentaires) ainsi que les principales préoccupations
identifiées lors de l'analyse des données.

Chaque profil est soumis automatiquement à l'API, et les routines générées sont
exportées dans un document imprimable prévu pour une relecture experte. Le
script de validation sert également de test de non-régression : il enregistre
une exécution de référence, ce qui permet de mesurer précisément l'effet de
toute modification ultérieure de l'algorithme de scoring.

## Limite reconnue

**La validation par un professionnel de la cosmétique n'a pas pu être réalisée
dans le cadre de ce projet**, faute d'accès à un conseiller beauté ou à un
représentant de la boutique. Le document de relecture a été produit et reste
disponible, mais il n'a pas été rempli par un expert.

Une auto-évaluation a donc été menée sur les vingt-deux profils. Elle permet
d'identifier les erreurs manifestes, mais ne remplace pas un avis professionnel,
notamment sur les questions de compatibilité entre actifs et de
contre-indications cutanées.

## Résultats de l'auto-évaluation

Sur 22 profils testés : 21 génèrent une routine complète, 1 ne renvoie aucun
produit, aucune erreur technique n'a été relevée.

### Cas jugés satisfaisants

Les profils correspondant aux segments les mieux couverts du catalogue
produisent des routines cohérentes et complètes. Par exemple, le profil
« rougeurs et sensibilité » génère une routine de six étapes entièrement
composée de produits explicitement formulés pour peaux sensibles. Les profils
« taches pigmentaires », « rides et fermeté » et « acné adulte » donnent des
résultats du même niveau.

### Cas douteux identifiés

| Profil | Observation | Nature du problème |
|---|---|---|
| B02 — Déodorant peau sensible | Un acide exfoliant pour le visage et une huile essentielle sont proposés pour des aisselles irritées | Contre-indication possible — à confirmer par un professionnel |
| C01 — Chute de cheveux | Une coloration végétale est proposée en soin ciblé | Pertinence discutable |
| I04 — Sommeil et stress | Ginkgo Biloba (mémoire) et gingembre sont proposés pour l'endormissement | Association préoccupation/produit imprécise |
| I03 — Digestion | Une tisane destinée aux nourrissons est proposée à une adulte | Le champ « public cible » n'est pas encore extrait |

### Corrections apportées à la suite de la validation

Le protocole a permis d'identifier et de corriger trois défauts avant toute
mise en production :

1. **Absence de routine pour les compléments alimentaires.** L'assemblage des
   routines parcourait uniquement les étapes des soins topiques (nettoyage,
   hydratation, protection). Les compléments, dont l'étape est
   `complement_oral`, n'étaient jamais retenus : quatre profils sur vingt-deux
   ne renvoyaient donc aucun résultat malgré plus de trente produits
   correspondants. Une logique de « cure » spécifique a été ajoutée.

2. **Confusion entre digestion et minceur.** Une cliente signalant des
   ballonnements se voyait proposer des produits amincissants, les descriptions
   partageant des termes comme « transit » ou « drainant ». Au-delà de l'erreur
   de catégorie, orienter vers des produits de perte de poids une personne qui
   n'en a pas fait la demande constitue une suggestion inappropriée. Deux
   correctifs ont été apportés : le titre du produit prime désormais sur la
   description dans le classement des préoccupations, et une table de conflits
   empêche certaines préoccupations de se répondre entre elles.

3. **Aliments classés comme compléments.** Des produits d'épicerie (lait en
   poudre, poudre de caroube) étaient assimilés à des compléments alimentaires
   par la présence du mot « poudre ». Les motifs de reconnaissance ont été
   affinés.

## Limites du catalogue mises en évidence

La validation a également révélé des manques qui ne relèvent pas de
l'algorithme mais de l'offre elle-même :

| Profil | Produits correspondants | Conséquence |
|---|---|---|
| C02 — Pellicules + cuir chevelu gras | 0 | Aucune recommandation possible |
| V11 — Peau normale | 2 | Routine incomplète |
| C03 — Cheveux abîmés | 2 | Routine incomplète |
| B01 — Peau du corps sèche | 3 | Routine réduite |

Ces résultats confirment l'analyse initiale des données : le catalogue est
dense sur certaines préoccupations (digestion, immunité, taches, rides) et
très mince sur d'autres. C'est également ce qui a motivé le choix de structurer
le moteur autour des préoccupations plutôt que des types de peau, ces derniers
ne comptant que 8 à 27 produits chacun.

## Suite recommandée

1. Faire remplir le document de relecture par un conseiller beauté dès qu'un
   accès au client est possible. L'objectif à atteindre est zéro produit jugé
   « mauvais » : en conseil cosmétique, une recommandation inadaptée n'est pas
   une simple erreur de classement mais une perte de confiance.
2. Signaler au client les préoccupations non couvertes par le catalogue, qui
   constituent autant d'opportunités commerciales.
3. Extraire le champ « public cible » (adulte, enfant, nourrisson), aujourd'hui
   prévu dans le modèle de données mais non alimenté.
4. Rejouer le test de non-régression après chaque modification du scoring.
