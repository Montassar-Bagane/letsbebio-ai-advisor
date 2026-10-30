# Product data model — AI recommendation engine

Version 1.0 · based on the full production catalogue (dump of 2026-05-26)
Status: implemented and validated against a working prototype.

---

## 1. Summary

The WooCommerce taxonomy cannot drive recommendations on its own:

- product tags: **0**
- skin-type attribute: present on **6 products out of 612**
- categories: 69, but products carry ~4 each and include merchandising buckets
  (`Accueil` 239 products, `Promos` 97) that say nothing about the product

The information a recommendation engine needs does exist — inside the product
descriptions, which average 1,414 characters and are written to a consistent
pattern ("*destiné aux peaux mixtes à grasses et à tendance acnéique*").

**So the model is an enrichment layer**: a derived, structured record built on
top of WooCommerce, regenerated from the source data on demand. WooCommerce
stays the single source of truth for price, stock and content. Nothing is
re-keyed by hand, and nothing in the store has to be re-tagged.

The pipeline runs in ~3 seconds over 607 products and costs nothing.

---

## 2. The record

One JSON object per published product.

### 2.1 Commercial fields — copied verbatim, never inferred

| Field | Type | Source |
|---|---|---|
| `id` | int | `posts.ID` |
| `name` | string | `post_title` |
| `slug` | string | `post_name` |
| `brand` | string | taxonomy `product_brand` |
| `categories` | string | `product_cat`, merchandising buckets removed |
| `price` | decimal | `_price` |
| `regular_price` | decimal | `_regular_price` |
| `stock` | int | `_stock` |
| `stock_status` | enum | `_stock_status` |
| `total_sales` | int | `total_sales` |
| `rating` | decimal | `_wc_average_rating` |
| `image_id` | int | `_thumbnail_id` |

These must never pass through an inference step. Price and stock shown to a
shopper have to be exactly what WooCommerce holds.

### 2.2 Derived fields — extracted from text

| Field | Type | Cardinality |
|---|---|---|
| `product_format` | enum | exactly 1 |
| `zone` | enum | exactly 1 |
| `skin_type` | enum[] | 0–n |
| `hair_type` | enum[] | 0–n |
| `concerns` | enum[] | 1–4, most specific first |
| `usage_time` | enum[] | 1–2 |
| `routine_step` | enum | exactly 1 |
| `key_ingredients` | string[] | 0–6 |
| `volume_size` | string \| null | 0–1 |
| `is_pack` | bool | 1 |
| `pack_contents_ids` | int[] | 0–n |
| `benefit_summary` | string | 1 |
| `confidence` | float 0–1 | 1 |
| `extraction_method` | string | 1 |

---

## 3. Controlled vocabularies

Values come from fixed enums, never free text. Free tagging would produce
`peau grasse`, `peaux grasses` and `Peau Grasse` as three distinct values and
make the data unqueryable.

**`concerns`** — the primary recommendation axis (25 values)

*Skin:* taches_pigmentaires · rides_age · deshydratation · imperfections_acne ·
rougeurs_sensibilite · exces_sebum · eclat_teint · protection_solaire ·
cernes_poches · pores_dilates · hygiene

*Hair:* chute_cheveux · pellicules · cheveux_abimes

*Internal:* digestion · immunite · sommeil_stress · energie_tonus ·
articulations · memoire_concentration · glycemie_tension · fertilite ·
sport_nutrition · minceur_detox · cheveux_peau_ongles

Plus `aucun` for products with no health or beauty claim.

**`skin_type`** — normale · seche · mixte · grasse · sensible · acneique ·
mature · tous

**`hair_type`** — secs · gras · normaux · abimes · colores · boucles_frises ·
pellicules · chute · tous

**`zone`** — visage · yeux · levres · mains · pieds · bouche · cheveux · corps ·
oral · maison · polyvalent

**`routine_step`** — nettoyage → tonification → traitement → hydratation →
protection · soin_cible · complement_oral · non_applicable

**`usage_time`** — matin · soir · indifferent

**`product_format`** — 35 values (nettoyant, serum, creme_hydratante, masque,
shampooing, complement_gelules, aliment, epice, accessoire…).

### Why `zone` is a separate field

`product_format` says *what a product is*; `zone` says *where it goes*. A lip
scrub and a face scrub are both `gommage`. Without `zone`, the prototype opened
a facial routine with a lip scrub. Format alone is not enough.

---

## 4. Rules that protect recommendation quality

**Empty is not "suitable for all."** If a description does not state a skin
type, `skin_type` stays `[]`. Defaulting to `tous` is how an engine ends up
recommending everything to everyone.

**A stated mismatch disqualifies.** If a product lists skin types and the
shopper's type is not among them, it is excluded — not down-ranked. A product
formulated for oily skin should never reach someone with sensitive skin.
A product with no stated type remains eligible, because 172 topical products
have none.

**Concerns are ordered.** Position 0 is the primary purpose. The engine scores
a primary match materially higher than a secondary one, and the interface says
which it was ("cible en priorité" vs "traite aussi").

**Confidence travels with the record.** Extraction certainty is a field, not a
filter. Low-confidence products rank lower rather than disappearing, and the QA
report lists them for review.

**Commercial signals stay weak.** Rating and sales volume are small tiebreakers.
A bestseller must not outrank a better-suited product — that turns a
recommendation engine into a promotion engine.

---

## 5. Coverage — what the model actually holds

| | Count |
|---|---|
| Published products modelled | 607 |
| `product_format` assigned | 607 (100%) |
| `concerns` assigned | 607 (100%) |
| Topical products | 282 |
| — with a stated `skin_type` | 110 |
| — with no stated type (still eligible) | 172 |
| Packs identified | 52 |
| — with components resolved | 20 |
| Products needing review (`confidence` < 0.5) | 5 |

**Products per concern** (recommendation depth):

digestion 89 · energie_tonus 75 · immunite 72 · glycemie_tension 71 ·
sommeil_stress 62 · rougeurs_sensibilite 59 · minceur_detox 54 ·
rides_age, taches_pigmentaires, deshydratation ~50–60 each

**Products per skin type:** grasse 27 · mature 27 · sensible 26 · acneique 25 ·
seche 20 · mixte 13 · normale 8

### The decision this coverage forced

Concern depth is 50–90 products; skin-type depth is 8–27. A recommender
organised around skin type would offer a "normal skin" shopper a choice of 8
products.

**So concerns are the primary axis and skin type is a secondary filter.** This
also matches how the store already thinks — its own packs are named *Pack
anti-taches* and *Routine peau sensible*, never *Pack peau normale*.

---

## 6. Packs as routine templates

The catalogue contains 52 packs. They are hand-composed by the brand and are
therefore the best available cold-start data: expert-validated routines for
specific concerns.

**Structural limitation:** packs are stored as WooCommerce `simple` products,
not `grouped` (`grouped` count = 0). There is no database link between a pack
and its contents. Composition exists only in the description text.

Components were recovered by matching known product names inside pack
descriptions, weighted by word rarity, requiring every identifying word to be
present. That yields **20 packs with trustworthy contents out of 52**, chosen
deliberately: a wrong component silently corrupts every routine built from that
template, while a missing one costs nothing.

**Recommendation:** ask the client for a plain list of what each pack contains.
Twenty minutes of their time beats any matching algorithm, and converting the
packs to WooCommerce `grouped` products would make the link permanent.

---

## 7. Pipeline

```
WooCommerce (MySQL)
   └─ export.sql            → products.jsonl     raw text + commercial fields
        └─ enrich_rules.py  → products_enriched  derived fields, rule-based
             └─ resolve_packs.py                 pack composition
                  └─ finalize.py                 catalogue.json · routines.json · qa_report.txt
                       └─ moteur.html            questionnaire + scoring + routine
```

Fully re-runnable. When the client adds products, re-run and the model updates.

**Extraction is rule-based today** — French cosmetic copy is formulaic enough
that patterns recover most of the signal at zero cost. The same schema is
produced by an LLM pass (`enrich.py`), which is the upgrade path for:

- `key_ingredients` (rules catch a known list only)
- `benefit_summary` (rules fall back to the first sentence)
- `pack_contents` (rules cannot read composition from prose)
- products where `confidence` is low

Because the schema is identical, this can be applied to *only* the low-
confidence subset rather than the whole catalogue.

---

## 8. Open questions for the client

1. **Scope** — beauty only, or also supplements and food? *Compléments
   alimentaires* is the largest real category (192) and the catalogue already
   links it to beauty via *Cheveux, peau et ongles*.
2. **Pack composition** — can they supply the contents of the 52 packs?
3. **Thin skin-type segments** — normal (8) and combination (13) skin cannot
   support a varied routine. Enrich the descriptions, or accept that the engine
   leads on concerns for these profiles?
4. **The `pa_type-de-peau` attribute** exists on 6 products. Is that an
   abandoned experiment or the start of a rollout? If the latter, the engine
   should read it as authoritative and override extraction.
5. **API ownership** — if the LLM pass is used in production, it runs on every
   session and needs the client's own account and billing from day one.

---

## Appendix — example record

```json
{
  "id": 1330,
  "name": "Écran solaire peau sensible SPF 50 Algovita",
  "brand": "Algo Vita",
  "price": "89",
  "stock_status": "instock",
  "rating": "0",

  "product_format": "solaire",
  "zone": "visage",
  "skin_type": ["sensible"],
  "hair_type": [],
  "concerns": ["protection_solaire", "rougeurs_sensibilite"],
  "usage_time": ["matin"],
  "routine_step": "protection",
  "key_ingredients": ["dioxyde de titane"],
  "volume_size": "50 ml",
  "is_pack": false,
  "pack_contents_ids": [],
  "benefit_summary": "Protection solaire haute pour peaux sensibles.",
  "confidence": 0.95,
  "extraction_method": "rules_v2"
}
```
