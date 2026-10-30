# WordPress plugin

```bash
make plugin        # from the project root — creates reco-engine.zip
```

Plugins → Add New Plugin → Upload Plugin → select the zip → Activate.
Then **Settings → Moteur de recommandation** and set the API URL. The status
line confirms the connection and reports the product count.

## Three ways to show it

| Where | How | Needs a language model |
|---|---|---|
| Floating bubble on every page | tick **Conseiller flottant** in the settings — no shortcode | yes |
| Dedicated advice page | `[conseiller_beaute]` | yes |
| Guided questionnaire | `[moteur_recommandation]` | no (optional free-text box) |

**The floating bubble is usually the right choice.** Advice is wanted while
the customer is looking at a product, not on a page they must navigate away
to. The conversation is kept in `sessionStorage`, so it follows the customer
from page to page and disappears when they leave.

If a page contains the `[conseiller_beaute]` shortcode, the bubble is
suppressed on that page so there are never two chats at once.

## How it connects

The browser never calls the API directly. It calls WordPress at
`/wp-json/reco/v1/…`, which forwards the request server-side. Three
consequences: no CORS configuration, the API address stays private, and there is
a single place to add logging or throttling later.

## Files

```
reco-engine/
├── reco-engine.php     settings page, REST proxy, shortcodes
└── assets/
    ├── reco.css        shared styles for both interfaces
    ├── reco.js         guided questionnaire
    └── chat.js         conversational adviser
```
