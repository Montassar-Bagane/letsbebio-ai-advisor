#!/usr/bin/env python3
"""
enrich.py — turn raw WooCommerce product text into structured attributes
for the recommendation engine.

Input :  products.jsonl          (from export.sql)
Output:  products_enriched.jsonl (one enriched product per line)

Resumable: re-running skips products already in the output file.

Setup:
    python3 -m venv .venv && source .venv/bin/activate
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python enrich.py                # all products
    python enrich.py --limit 12     # test on 12 first
"""

import argparse
import html
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from anthropic import Anthropic

MODEL = "claude-sonnet-5"   # swap to "claude-haiku-4-5-20251001" for a cheaper pass
BATCH_SIZE = 6              # products per API call
WORKERS = 4                 # parallel calls
MAX_DESC_CHARS = 2500

IN_FILE = Path("products.jsonl")
OUT_FILE = Path("products_enriched.jsonl")

# ---------------------------------------------------------------------------
# Controlled vocabularies — derived from the actual catalogue.
# Fixed enums are what make the output queryable. Do not let the model invent.
# ---------------------------------------------------------------------------

VOCAB = {
    "product_format": [
        "nettoyant", "lotion_tonique", "demaquillant", "serum", "creme_hydratante",
        "contour_yeux", "masque", "gommage", "savon", "huile_visage", "solaire",
        "shampooing", "apres_shampooing", "masque_capillaire", "huile_capillaire",
        "coloration_vegetale", "lait_corps", "deodorant", "dentifrice", "bain",
        "huile_vegetale", "hydrolat", "huile_essentielle", "argile", "poudre_plante",
        "complement_gelules", "complement_poudre", "tisane", "aliment", "epice",
        "huile_alimentaire", "accessoire", "menage", "pack", "autre",
    ],
    "skin_type": [
        "normale", "seche", "mixte", "grasse", "sensible", "acneique", "mature", "tous",
    ],
    "hair_type": [
        "secs", "gras", "normaux", "abimes", "colores", "boucles_frises",
        "pellicules", "chute", "tous",
    ],
    "concerns": [
        "taches_pigmentaires", "rides_age", "deshydratation", "imperfections_acne",
        "rougeurs_sensibilite", "exces_sebum", "eclat_teint", "protection_solaire",
        "cernes_poches", "pores_dilates", "chute_cheveux", "pellicules",
        "cheveux_abimes", "minceur_detox", "digestion", "immunite", "sommeil_stress",
        "energie_tonus", "articulations", "memoire_concentration", "glycemie_tension",
        "fertilite", "sport_nutrition", "cheveux_peau_ongles", "hygiene", "aucun",
    ],
    "usage_time": ["matin", "soir", "indifferent"],
    "routine_step": [
        "nettoyage", "tonification", "traitement", "hydratation", "protection",
        "soin_cible", "complement_oral", "non_applicable",
    ],
    "target_audience": ["adulte", "enfant", "bebe", "homme", "femme", "tous"],
}

SYSTEM_PROMPT = f"""You extract structured product attributes for a beauty and
wellness recommendation engine. The catalogue is a Tunisian natural-products
store: skincare, haircare, supplements, food, eco-household.

Product text is in French. Return field VALUES from the controlled vocabularies
only — never invent a value, never translate the enum tokens.

CONTROLLED VOCABULARIES
{json.dumps(VOCAB, ensure_ascii=False, indent=2)}

For each product return exactly this object:

{{
  "id": <int, copy from input>,
  "product_format": "<one value>",
  "skin_type": [<0-n values; [] if not a skin product>],
  "hair_type": [<0-n values; [] if not a hair product>],
  "concerns": [<1-4 values, most specific first>],
  "usage_time": [<1-2 values>],
  "routine_step": "<one value>",
  "key_ingredients": [<up to 6, lowercase French, e.g. "aloe vera", "huile de jojoba">],
  "volume_size": "<e.g. '50 ml', '100 g', '60 gélules'; null if absent>",
  "is_pack": <true|false>,
  "pack_contents_raw": [<product names named in the text; [] if not a pack>],
  "benefit_summary": "<one French sentence, max 20 words, for display to shoppers>",
  "confidence": <0.0-1.0 — how well the text supported this extraction>
}}

RULES
- Only assign skin_type / hair_type when the text actually supports it. An
  unscented body oil is not "tous" by default — use [] when unstated.
- "Peaux mixtes à grasses" -> ["mixte","grasse"]. "Peaux à tendance acnéique"
  -> add "acneique". "Peaux sensibles" -> ["sensible"].
- Oral supplements: routine_step "complement_oral", usage_time from the dosage
  instructions if stated, else ["indifferent"], skin_type [] unless the product
  explicitly targets skin.
- Food, spices, household and accessories: concerns ["aucun"] unless the text
  makes a real health claim; routine_step "non_applicable".
- is_pack true when the title or text says Pack / Duo / Trio / Coffret /
  Routine / Set AND describes multiple items. Beware false friends: "Lotion",
  "Noisette" and "Coloration" are not packs.
- pack_contents_raw: copy the component product names verbatim from the text.
- confidence below 0.5 means the text was too thin — say so honestly.

Return a JSON array of these objects, one per input product, in the same order.
Output raw JSON only: no prose, no markdown fences."""

_write_lock = threading.Lock()
client = Anthropic()


def clean(text: str) -> str:
    """Strip HTML tags and entities, collapse whitespace."""
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def render(p: dict) -> str:
    return (
        f"--- PRODUCT {p['id']} ---\n"
        f"NAME: {p.get('name','')}\n"
        f"BRAND: {p.get('brand') or 'unknown'}\n"
        f"CATEGORIES: {p.get('categories') or 'none'}\n"
        f"SHORT: {clean(p.get('short_desc',''))[:800]}\n"
        f"DESCRIPTION: {clean(p.get('description',''))[:MAX_DESC_CHARS]}\n"
    )


def parse_json(raw: str):
    """Model output -> list. Tolerates stray fences or preamble."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def process_batch(batch: list) -> list:
    payload = "\n".join(render(p) for p in batch)
    last_err = None

    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": payload}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            results = parse_json(text)

            by_id = {p["id"]: p for p in batch}
            out = []
            for r in results:
                src = by_id.get(r.get("id"))
                if not src:
                    continue
                # carry the hard commercial facts through untouched
                r.update({
                    "name": src.get("name"),
                    "brand": src.get("brand"),
                    "categories": src.get("categories"),
                    "price": src.get("price"),
                    "regular_price": src.get("regular_price"),
                    "stock": src.get("stock"),
                    "stock_status": src.get("stock_status"),
                    "total_sales": src.get("total_sales"),
                    "rating": src.get("rating"),
                    "image_id": src.get("image_id"),
                    "slug": src.get("slug"),
                })
                out.append(r)
            return out

        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  retry {attempt + 1}/3 — {type(e).__name__}: {e}", file=sys.stderr)

    ids = [p["id"] for p in batch]
    print(f"  FAILED batch {ids}: {last_err}", file=sys.stderr)
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="process only the first N products")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set.")
    if not IN_FILE.exists():
        sys.exit(f"{IN_FILE} not found — run export.sql first.")

    products = []
    for line in IN_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                products.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  skipped unparseable line: {line[:80]}", file=sys.stderr)

    done = set()
    if OUT_FILE.exists():
        for line in OUT_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    pass

    todo = [p for p in products if p["id"] not in done]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(products)} products | {len(done)} already done | {len(todo)} to process")
    if not todo:
        return

    batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    completed = 0

    with OUT_FILE.open("a", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for results in pool.map(process_batch, batches):
                with _write_lock:
                    for r in results:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush()
                completed += len(results)
                print(f"  {completed}/{len(todo)}", end="\r", flush=True)

    print(f"\nDone. {completed} products written to {OUT_FILE}")


if __name__ == "__main__":
    main()
