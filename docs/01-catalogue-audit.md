# WooCommerce Product Data Audit — letsbebio

Source: full MySQL dump (2026-05-26), imported locally. Table prefix `wp_11e347_`.
No admin access needed — this covers **all 1,073 products**, not a sample.

---

## Headline numbers

| | |
|---|---|
| Products total | 1,073 |
| **Published** | **612** |
| Draft | 323 |
| Trash | 138 |
| Product types | 593 simple, 10 variable, **0 grouped**, 0 external |
| Categories | 69 (3 levels deep) |
| Brands | 41 |
| Tags | **0** |
| Avg description length | 1,414 chars |
| Products with empty description | 60 |

Store was migrated from PrestaShop (`_wpmigrate_presta_product_id` on 1,056 products) — that explains the category slugs like `19-complements-alimentaires`.

---

## 1. What product categories exist?

69 categories, three levels. Top level:

| Category | Products |
|---|---|
| Accueil | 239 |
| Compléments alimentaires | 192 |
| Soin et beauté | 163 |
| Alimentation | 137 |
| Promos | 97 |
| Bien-être | 89 |
| Ecolo | 68 |
| Packs et coffrets | 45 |
| Destockage / Racine / Uncategorized | 0–1 |

**Beauty branch** (the relevant one for a skin/hair engine):

```
Soin et beauté (163)
├── visage (101)
│   ├── Gels, sérums et crèmes hydratantes (53)
│   ├── savons et masques (15)
│   ├── Soins Bouche et dents (5)
│   ├── Soin des yeux (4)
│   └── démaquillants et lotions (3)
├── cheveux (54)
│   ├── Shampoings, Après-shampoings et masques (22)
│   └── sérums et huiles capillaires (8)
├── corps (50)
│   ├── lait et crèmes pour le corps (34)
│   └── déodorants (10)
└── Enfants (3)
```

**Two problems:**

- `Accueil`, `Promos`, `Destockage` are **merchandising buckets, not real categories**. "Accueil" (=homepage) holds 239 products. These must be excluded from any recommendation logic.
- **Category assignment is noisy.** Examples pulled at random:
  - *Poudre de Romarin* (a cooking herb) → `cheveux`, `corps`, `Soin et beauté`
  - *Huile d'Avocat Bio* → 7 categories including `Kéto`, `Huiles végétales`, `Bien-être`
  - *Vitamine B Complexe* → 7 categories

  Products average 4 categories. Categories cannot be trusted as a clean signal.

---

## 2. What information does each product contain?

**Populated and usable:**

| Field | Coverage |
|---|---|
| `post_title` | 100% |
| `post_content` (long description) | 552/612 — avg 1,414 chars, HTML |
| `post_excerpt` (short description) | 604/612 |
| `_price` / `_regular_price` | ~100% |
| `_sale_price` | 50 products |
| `_stock`, `_stock_status` | 626 |
| `_thumbnail_id` (image) | 1,033 |
| `total_sales` | 626 |
| `_wc_average_rating`, `_wc_review_count` | 626 |
| Brand (`product_brand`) | 514 assignments, 41 brands |

**Missing:**

- **No SKU** — `_sku` is empty across the board.
- No ingredient field, no volume/size field, no usage-step field, no "use morning/evening" field.
- ~30 `bzotech_*` meta keys on 623 products — these are theme layout settings (sidebar position, typography, colors). **Ignore entirely.**

**The important finding:** the real product intelligence is buried in the free-text description. A sample:

> *Gel nettoyant purifiant AlgoVita* — short description states: cleanses gently, regulates sebum, prevents blemishes. **"Peaux mixtes à grasses et peaux à tendance acnéique."** 150ml pump bottle.

> *Savon liquide Jardin Amazygh* — description is literally structured as Q&A: Where to apply? / **For which skin type? → sensitive skin** / What does it do? / **When to apply? → morning and/or evening** / How to use it.

Skin type, concern, usage timing, and application steps are all there — as prose, not as fields.

---

## 3. Are there product attributes?

Technically yes, practically no.

| Attribute | Values | Products using it |
|---|---|---|
| `pa_type-de-peau` (Type de Peau) | Peau Normale-Sèche, Peau Mixte-Grasse | **6** |
| `pa_teinte` (teinté) | Beige, Rose | 10 |
| `pa_poids` (Poids) | 200gr, 1 Kg | 2 |

**Six products out of 612 have a skin type attribute.** This is effectively unused.

268 products have `_product_attributes` (custom per-product attributes, not global) — worth a second pass, but these are free-form and inconsistent by nature.

---

## 4. Are there product tags?

**No. Zero.** The `product_tag` taxonomy has no terms at all.

There *is* `product_brand` — 41 brands, 514 assignments. Main beauty brands: **AlgoVita** (dominant in skincare), Bioherbs, Phytokad, Carthage Nutrition, Herbéos, Jardin Amazygh, Elixir, Merci Fit.

---

## 5. Are products organized by skin type / hair type?

**No.** Only by product *format* (visage / cheveux / corps), never by *skin type* or *concern*.

The information exists but only in unstructured text — in titles and descriptions:

- `Ecran Solaire anti-âge éclaircissant Invisible **(Peaux Mixtes à Grasses)** AlgoVita`
- `Duo éclaircissant **peau sensible** Algovita`
- `Routine **peau grasse transpirante**`
- `...destiné pour les **peaux mixtes à grasses** et les **peaux à tendance acnéique**` (in description body)

Concerns visible in the catalogue: anti-taches / éclaircissant, anti-rides / anti-âge, peau sensible, peau grasse / acnéique, hydratation, solaire, anti-imperfections.

None of this is queryable today.

---

## 6. Are there existing routines or packs?

**Yes — and this is the strongest asset in the dataset.**

- Category `Packs et coffrets`: **45 products**
- ~50 products with Pack / Duo / Trio / Routine in the title

They are already organised the way a recommendation engine would want to output:

| Pack | Implied target |
|---|---|
| Routine peau sensible AlgoVita | sensitive skin |
| Routine anti-tâches Algovita | pigmentation |
| Routine peau grasse transpirante | oily skin |
| Pack éclaircissant anti-imperfections peau grasse | oily + brightening |
| Duo ANTI-RIDES — Soin de Nuit | anti-ageing, evening |
| Pack hydratation hiver Algovita | hydration, seasonal |
| Trio solaire Algovita | sun protection |
| Pack Anti-Taches persistantes cure complète | pigmentation, full course |

**Critical limitation:** these packs are `simple` products, **not** `grouped` products (grouped count = 0). So a pack has **no database link to the individual products inside it**. The composition exists only in the description text.

---

## What this means for the recommendation engine

The structured taxonomy is not usable as a recommendation signal. The signal is in the prose.

Recommended approach — **an enrichment layer**, not a re-tagging project in WooCommerce:

1. **Extract, don't re-enter.** Run the 612 published products' title + short description + description through an LLM to extract structured fields. The text is rich and consistent enough (avg 1,414 chars) for this to work well.

2. **Target schema:**

```
product_id, name, brand, price, stock, image, url
category_clean          (single primary category, merchandising buckets stripped)
product_format          (cleanser / serum / cream / oil / mask / SPF / supplement / food …)
skin_type[]             (normal, dry, combination, oily, sensitive, acne-prone)
hair_type[]             (dry, oily, damaged, curly, dandruff …)
concerns[]              (pigmentation, ageing, dehydration, blemishes, sun, hair loss …)
usage_time[]            (morning, evening, both)
routine_step            (cleanse → tone → treat → moisturise → protect)
key_ingredients[]
volume_size
is_pack                 (bool)
pack_contents[]         (resolved product_ids — see 3 below)
```

3. **Mine the existing packs.** The ~50 packs are hand-built expert routines. Parsing their descriptions to resolve component products gives ready-made, brand-validated routine templates — far better cold-start data than anything generated from scratch.

4. **Exclude:** 323 drafts, 138 trashed, 60 products with no description, and the Accueil / Promos / Destockage categories.

Two validation questions worth putting to the client before building:
- Is the `pa_type-de-peau` attribute intentionally being rolled out (6 products = a pilot), or abandoned?
- Should the engine cover supplements and food too, or beauty only? *Compléments alimentaires* is the largest real category (192) and the catalogue already links them to beauty via `Cheveux, peau et ongles` (37 products).
