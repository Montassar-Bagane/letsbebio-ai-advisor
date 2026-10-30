# Architecture — from prototype to production

Version 1.0 · companion to `data_model.md`

---

## 1. What exists today, and what it is not

| Built | Status |
|---|---|
| Extraction pipeline (SQL → structured catalogue) | working, ~3 s, zero cost |
| 607 products modelled, 20 routine templates | validated |
| Scoring + routine assembly | working, deterministic |
| Demo interface | single HTML file, local |

**What it is not:** a service. It reads a static JSON file produced from a
database dump. Nobody but the developer can reach it, and the data is a
snapshot, not live.

Three things must change for production: the catalogue must refresh, the engine
must be reachable over the network, and a shopper must be able to arrive from
the store.

---

## 2. Where the AI belongs — and where it does not

This matters more than the deployment choice, so it comes first.

The engine today is a scoring function. It is not machine learning and does not
need to be. **Deterministic matching is the right default**, because:

- it explains itself ("cible en priorité Taches") — required for beauty advice
- it is reproducible: identical input, identical output, every time
- it cannot invent a product that does not exist
- it costs nothing per query and answers instantly

Putting a language model in charge of *choosing products* would sacrifice all
four, and buy nothing the scoring does not already do.

### Where a model earns its place

**A — Understanding free-text input.** A shopper types *"j'ai des taches
depuis ma grossesse et la peau qui tire, budget 100 dinars"*. Converting that
into `{concerns: [taches_pigmentaires, deshydratation], skin_type: [seche],
budget: 100}` is exactly what an LLM is good at and what rules handle badly.
The model produces the *profile*; the deterministic engine still picks the
products.

**B — Writing the explanation.** Turning a scored result into a sentence a
shopper trusts: *"Ce sérum cible les taches, et sa formule sans parfum convient
à votre peau sensible."* Grounded in the structured record, so it cannot claim
anything the data does not support.

**C — Enriching thin records.** The existing `enrich.py` — run only on
low-confidence products, not the whole catalogue.

### The rule that keeps this safe

> The model may interpret the question and phrase the answer.
> It may not decide which products are returned.

Retrieval stays deterministic and auditable. This is the standard shape for
recommendation with LLMs, and it is what makes the system defensible when a
client asks why a product was suggested.

---

## 3. Deployment options

### Option A — Static, client-side (what exists now)

Catalogue exported as JSON, all logic in the browser.

*For:* no server, no hosting cost, instant, works offline.
*Against:* full catalogue downloaded by every visitor (~1.5 MB), prices go stale
between exports, no analytics, no free-text input.

**Verdict:** correct for the demo and for internal validation. Not for a live
store.

### Option B — API service + WordPress front end  ← recommended

```
  Shopper
     │
     ▼
  WordPress page  ──── questionnaire (JS widget on the store)
     │  POST /recommend
     ▼
  Recommendation API   (Python: FastAPI or Flask)
     ├── catalogue.json in memory      ← rebuilt nightly
     ├── deterministic scoring
     └── optional LLM: parse free text / write explanation
     │
     ▼
  WooCommerce REST API ──── live price + stock at render time
```

*For:* catalogue stays server-side, prices verified live, requests are
loggable so recommendation quality can be measured, LLM key never exposed.
*Against:* a service to host and keep running.

**Refresh:** a nightly job re-runs the pipeline against the live database and
swaps `catalogue.json` atomically. Product content changes slowly; price and
stock are fetched live at display time, so a stale catalogue never shows a
wrong price.

### Option C — WordPress plugin, all in PHP

Rewrite the scoring in PHP, store derived fields in `postmeta`.

*For:* one system, no extra hosting, works with existing WooCommerce caching.
*Against:* the extraction pipeline is Python and would be rewritten or kept
separate anyway; PHP is a poor fit for the enrichment work; slowest to iterate.

**Verdict:** the right end state if the client wants zero external
dependencies, but the wrong thing to build first.

---

## 4. API contract

Designing this now keeps the front end independent of the implementation — the
stack can change without the store noticing.

### `POST /recommend`

```json
{
  "domain": "visage",
  "concerns": ["taches_pigmentaires"],
  "skin_type": "sensible",
  "usage_time": "soir",
  "budget_max": 120,
  "brand": null,
  "in_stock_only": true,
  "locale": "fr"
}
```

Response:

```json
{
  "profile": { "domain": "visage", "concerns": ["taches_pigmentaires"],
               "skin_type": "sensible", "matched_products": 19 },
  "routine": [
    { "step": "nettoyage", "position": 1,
      "product": { "id": 1204, "name": "...", "price": "24",
                   "in_stock": true, "url": "https://..." },
      "reason": "cible en priorité les taches",
      "match": { "concern": "primary", "skin_type": "explicit" } }
  ],
  "packs": [ { "id": 839, "name": "Pack ANTI-TACHES INTÉGRAL",
               "price": "180", "components": [1328, 196] } ],
  "alternatives": [ { "id": 194, "name": "...", "score": 18.4 } ],
  "meta": { "engine": "rules_v2", "generated_at": "2026-08-03T10:12:00Z" }
}
```

**Two deliberate choices.** Every recommendation carries a `reason` and a
`match` object, so the interface can always say why. And `matched_products` is
returned even when small — a profile with three matches should say so rather
than pad the list.

### `POST /interpret` (optional, LLM-backed)

Free text in, a `/recommend` request body out. Isolated in its own endpoint so
the engine works unchanged if it is switched off or unavailable.

---

## 5. Measuring whether recommendations are good

Currently untested. Without this, "the engine works" is an opinion.

**Before launch — expert review.** Build 15–20 realistic profiles (oily +
acne-prone, mature + pigmentation, dry sensitive winter…). Run each, print the
routines, have the client's beauty advisor mark each product *appropriate /
acceptable / wrong*. Target: zero "wrong", since a wrong product in beauty
advice is a trust failure, not a ranking miss.

This doubles as the regression test — re-run it after every scoring change and
compare.

**After launch — behavioural.**

| Metric | Question |
|---|---|
| Completion rate | do shoppers finish the questionnaire? |
| Click-through on recommendations | are the results credible? |
| Add-to-cart from recommendation | does it sell? |
| Empty-result rate by profile | which profiles have no catalogue depth? |
| Return rate on recommended items | were suggestions actually suitable? |

The empty-result metric matters most for the client: it turns "your catalogue
is thin for normal skin" from an opinion into a monthly number.

---

## 6. Phasing

| Phase | Deliverable | Depends on |
|---|---|---|
| 1 ✅ | Data model + extraction pipeline | — |
| 2 ✅ | Deterministic engine + demo | 1 |
| 3 | Expert validation on 20 profiles | client's advisor |
| 4 | API service, live price/stock | hosting decision |
| 5 | Questionnaire widget on the store | 4 |
| 6 | Free-text input + generated explanations | 5, API budget |
| 7 | Behavioural metrics, monthly review | 5 |

Phase 3 comes before any more building. There is no point optimising a scoring
function nobody has checked against expert judgement.

---

## 7. Decisions the client owns

1. **Hosting** — is there a server, or must this live inside WordPress?
2. **Live data** — can the API reach WooCommerce (REST key), or is a nightly
   export the only option?
3. **Expert time** — who reviews the 20 test profiles? Without this the engine
   ships unvalidated.
4. **LLM budget** — free-text input and generated explanations cost per query.
   Optional, and the engine works fully without them.
5. **Languages** — French only, or French + Arabic? This affects both the
   interface and the extraction vocabularies.

---

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Catalogue thin for some profiles (normal skin: 8 products) | weak or empty routines | lead on concerns; report empty-result rate to the client |
| Prices stale between exports | wrong price shown | fetch price and stock live at render |
| Extraction drifts as new products are added | quality decays silently | pipeline re-runs nightly; QA report reviewed monthly |
| 32 of 52 packs have unknown contents | incomplete routine templates | request the composition list from the client |
| LLM misreads free text | wrong profile → wrong routine | show the interpreted profile back to the shopper, editable |
