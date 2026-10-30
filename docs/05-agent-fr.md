# L'agent conversationnel

## 1. Du moteur à l'agent

La première version du système est un moteur de recommandation déterministe :
le client remplit un questionnaire, un algorithme de scoring classe les
produits, une routine est composée. Le parcours est fixe et connu à l'avance.

Un modèle de langage a ensuite été ajouté pour interpréter une phrase libre
(« j'ai des taches depuis ma grossesse et la peau sensible ») et la convertir
en profil structuré. Le système devient alors **assisté par IA**, mais reste un
pipeline : une entrée, une sortie, un seul passage.

**L'agent conversationnel introduit une différence de nature : une boucle.**
Le modèle appelle un outil, observe le résultat, et décide en fonction de ce
résultat quelle sera l'étape suivante. Ce chemin ne peut pas être écrit à
l'avance, car il dépend de ce que le client répond.

| | Pipeline | Agent |
|---|---|---|
| Nombre d'appels | 1 | variable (1 à 8) |
| Étape suivante | fixée par le code | décidée par le modèle |
| Mémoire | aucune | conversation complète |
| Outils | aucun | 3 |

## 2. Architecture

```
Client (WordPress)
   │  message + historique
   ▼
API /chat
   │
   ├─► Modèle de langage ──┐
   │                        │  décide quel outil appeler
   │   ◄────────────────────┘
   │
   ├─► lister_options()      ─┐
   ├─► chercher_produits()    ├─► moteur déterministe (scoring.py)
   ├─► construire_routine()  ─┘         │
   │                                     ▼
   │                            base WooCommerce (lecture seule)
   │
   └─► réponse en français + cartes produits
```

Le moteur de recommandation développé précédemment n'est pas remplacé : il
devient **l'outillage de l'agent**. Le travail d'extraction, de scoring et de
composition de routines est intégralement réutilisé.

### Les trois outils

| Outil | Rôle |
|---|---|
| `lister_options` | Renvoie les préoccupations et types de peau réellement présents au catalogue, avec le nombre de produits. Utilisé quand le modèle hésite sur une valeur. |
| `chercher_produits` | Recherche classée par pertinence pour un profil donné. |
| `construire_routine` | Routine ordonnée complète (nettoyer → tonifier → traiter → hydrater → protéger) avec le prix total. |

## 3. La règle de sécurité

> **Le modèle interprète la demande, choisit quel outil appeler, et rédige la
> réponse. Il ne décide jamais quels produits existent.**

Cette règle est appliquée par le code, pas seulement par la consigne :

- les cartes produits renvoyées à l'interface sont construites **uniquement à
  partir des identifiants retournés par les outils** ;
- si le modèle invente un nom de produit dans son texte, il n'existe aucune
  carte correspondante : rien n'est affiché, et l'invention ne peut pas être
  ajoutée au panier ;
- les prix et le stock sont relus dans la base au moment de la réponse, jamais
  repris du texte du modèle.

C'est le point le plus important de la conception. En conseil cosmétique, un
produit inventé ou un prix erroné n'est pas une imprécision : c'est une perte
de confiance, et potentiellement un risque pour le client.

## 4. Fonctionnement observé

Extrait d'une conversation de test réelle :

**Client :** « J'ai des boutons et la peau grasse »

L'agent traduit le langage courant en vocabulaire du catalogue
(`imperfections_acne`, `exces_sebum`, `type_peau: grasse`), appelle
`construire_routine`, et renvoie une routine de quatre étapes à 106,5 DT.

**Client :** « je dors mal aussi »

L'agent identifie un besoin entièrement différent, bascule vers le domaine
`interieur` (compléments alimentaires), appelle à nouveau l'outil et propose
une cure de deux produits à 33 DT — **sans répéter la routine précédente**.

Le second message déclenche une recherche dans une partie du catalogue qui
n'avait rien à voir avec la première. Aucun questionnaire à choix fixes ne
produit ce comportement.

## 5. Difficultés rencontrées et corrections

| Problème observé | Cause | Correction |
|---|---|---|
| Boucle infinie d'appels d'outils | Le modèle répétait le même appel sans jamais répondre | Détection des appels identiques ; au-delà de la limite, relance sans outils pour forcer une réponse rédigée |
| Cartes produits accumulées sur plusieurs tours | Tous les produits vus par un outil étaient conservés | Seul le dernier résultat pertinent est affiché |
| Totaux inventés (« 106 + 58 = 164 ») | Le modèle faisait l'addition lui-même | Le total provient du champ calculé par l'outil ; consigne explicite de ne jamais calculer |
| Prix annoncés en euros | Aucune devise dans la consigne | Devise imposée dans le prompt système |
| Décalage entre texte et cartes | Le modèle ne citait pas tous les produits renvoyés | Consigne : mentionner chaque produit renvoyé ; cure réduite de 3 à 2 produits |
| Dépassement de quota (HTTP 429) | Prompt système et schémas d'outils trop volumineux | Prompt réduit d'environ 75 % ; résultats d'outils tronqués ; historique limité à 8 tours ; réessai automatique en respectant le délai indiqué par le fournisseur |

Ces corrections illustrent un point méthodologique : **la plupart des défauts
d'un agent se corrigent au niveau de la consigne et des garde-fous, pas de
l'algorithme.** Les produits proposés étaient corrects dès le départ ; ce sont
la formulation et le contrôle de la boucle qui demandaient du travail.

## 5 bis. Comprendre le derja sans le générer

Une distinction s'est imposée à l'usage : **comprendre** l'arabe tunisien et
**le produire** sont deux problèmes de difficulté très différente.

Le modèle lit correctement « 3andi 7boub fi wajhi » : le contexte suffit. En
revanche, lorsqu'on lui demande de répondre en arabizi, il produit des phrases
malformées. Exemple obtenu en test :

> *3andek t3arraf t3arraf 3la n3a9lek el-barcha mta3ek ?*

La phrase est agrammaticale et comporte une répétition. La cause est
structurelle : l'arabizi est une convention de saisie, non une langue écrite
normalisée, et il est très peu représenté dans les données d'entraînement. Le
modèle devine la morphologie.

La règle retenue fait donc correspondre la langue de réponse à ce que le modèle
sait réellement produire :

| Écriture du client | Langue de réponse |
|---|---|
| Arabe | Arabe |
| Arabizi | Français |
| Français | Français |

Ce n'est pas une régression fonctionnelle. L'arabizi est la manière dont les
Tunisiens *écrivent*, pas une langue qu'ils ont besoin de se voir répondre, et
le français est celle du catalogue lui-même. Répondre clairement en français à
une question posée en arabizi constitue un meilleur service qu'une réponse en
derja approximatif.

Deux garde-fous complètent la consigne, car une instruction de prompt réduit
les artefacts sans les supprimer :

- les symboles phonétiques (ʕ, ħ, ɣ) produits par le modèle à la place des
  chiffres arabizi sont convertis avant affichage ;
- les identifiants internes du vocabulaire contrôlé (`taches_pigmentaires`)
  sont remplacés par les mots correspondants s'ils apparaissent dans le texte.

## 6. Indépendance vis-à-vis du fournisseur

L'agent communique avec n'importe quel service exposant une API compatible
OpenAI. Le changement de fournisseur se fait par trois variables
d'environnement, sans modification de code :

```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=...
LLM_MODEL=llama-3.3-70b-versatile
```

Fournisseurs testés : Groq (llama-3.3-70b), Google Gemini, Mistral. Un modèle
local via Ollama fonctionnerait de la même manière.

Ce choix a deux justifications. D'une part, il évite une dépendance à un
fournisseur unique pour un projet destiné à un client. D'autre part, les offres
gratuites changent fréquemment : pendant le développement, un modèle utilisé a
été retiré du service, et le basculement s'est fait en modifiant une ligne de
configuration.

## 7. Limite connue : le quota

Les offres gratuites limitent le nombre de jetons par minute. Avec Groq
(12 000 jetons/minute), une conversation consomme environ 4 000 jetons, soit
**trois échanges par minute au maximum**.

C'est suffisant pour une démonstration, insuffisant pour une boutique en
activité. Le passage à une offre payante lève la limite : à titre indicatif,
un modèle économique de type `gpt-4.1-mini` revient à moins d'un centime par
conversation.

Il s'agit d'un coût d'exploitation à prévoir, et non d'un défaut de conception :
le questionnaire guidé (`[moteur_recommandation]`) continue de fonctionner sans
aucun appel à un modèle, et reste disponible si le service de langage est
indisponible.

## 8. Intégration

Deux codes courts WordPress, servis par la même API :

| Code court | Interface | Modèle de langage |
|---|---|---|
| `[moteur_recommandation]` | Questionnaire guidé, routine, panier | Optionnel (champ texte libre) |
| `[conseiller_beaute]` | Conversation | Requis |

Le navigateur n'appelle jamais l'API directement : les requêtes transitent par
WordPress, ce qui évite toute configuration CORS, garde l'adresse du service
privée et centralise un éventuel contrôle de débit.

## 9. Ce que l'agent n'est pas

Honnêteté méthodologique : cet agent reste **borné**. Il dispose de trois
outils en lecture seule, ne peut pas modifier une commande, ne passe pas de
commande à la place du client, et ne mémorise rien entre deux visites. Sa
boucle est limitée à huit itérations.

Cette limitation est volontaire. Dans un contexte de conseil produit, un agent
capable d'agir sur les commandes ou les stocks introduirait un risque sans
bénéfice pour le client. L'autonomie a été accordée là où elle apporte quelque
chose — comprendre un besoin exprimé librement et décider quoi chercher — et
refusée partout ailleurs.
