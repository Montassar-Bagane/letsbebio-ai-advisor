#!/usr/bin/env python3
"""
resolve_packs.py  v2 — work out what is INSIDE each pack, without an API.

WHY v2: v1 counted every word equally, so "Creme anti-taches (Nuit) Algovita"
matched almost every night pack on the strength of creme + anti + nuit +
algovita, while the one word that actually identifies it (taches) was absent.

v2 fixes this with two rules:
  1. IDF weighting — a word appearing in 200 product names carries almost no
     evidence; a word appearing in 3 carries a lot. Matching is scored on
     weighted mass, not raw count.
  2. Anchor rule — the product's RAREST word must be present in the pack text.
     This alone kills the false positives above.

Inputs :  products.jsonl, products_enriched.jsonl
Outputs:  products_enriched.jsonl  (rewritten, pack contents filled)
          pack_matches.txt         (audit — read it)

Run:  python3 resolve_packs.py   then   python3 finalize.py
"""

import html
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

RAW_FILE = Path("products.jsonl")
ENR_FILE = Path("products_enriched.jsonl")
AUDIT    = Path("pack_matches.txt")

MIN_TOKENS   = 2      # product needs >= 2 usable words
MIN_MASS     = 0.72   # >= 72% of the product's evidence weight must be present
MIN_ANCHOR_W = 1.5    # a product with no word rarer than this is unmatchable
DISTINCTIVE  = 3.0    # words at/above this weight are identifying — ALL required

STOP = {
    "le", "la", "les", "de", "du", "des", "et", "au", "aux", "un", "une", "en",
    "pour", "avec", "sans", "sur", "par", "dans", "ou", "a", "l", "d", "se",
    "bio", "naturel", "naturelle", "naturels", "biologique", "pur", "pure",
    "ml", "cl", "gr", "g", "kg", "gelules", "gelule", "comprimes", "comprime",
    "capsules", "sachets", "sachet", "flacon", "pot", "tube", "boite",
    "pack", "duo", "trio", "coffret", "routine", "kit", "set", "lot",
    "produit", "produits", "soin", "soins", "nouveau", "promo", "offre",
}


def norm(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list:
    return [t for t in norm(text).split() if t not in STOP and len(t) > 2]


def main() -> None:
    for f in (RAW_FILE, ENR_FILE):
        if not f.exists():
            raise SystemExit(f"{f} not found.")

    raw = {}
    for line in RAW_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                r = json.loads(line)
                raw[r["id"]] = r
            except (json.JSONDecodeError, KeyError):
                pass

    enriched = [json.loads(l) for l in
                ENR_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]

    # --- IDF over product names -------------------------------------------
    name_tokens = {e["id"]: set(tokens(e.get("name") or "")) for e in enriched}
    N = len(name_tokens)
    df = Counter()
    for toks in name_tokens.values():
        df.update(toks)

    def weight(tok: str) -> float:
        return math.log(N / (1 + df[tok]))

    # show the operator what is being down-weighted
    generic = [(t, n, round(weight(t), 2)) for t, n in df.most_common(12)]

    # --- index of non-pack products ---------------------------------------
    index = []
    for e in enriched:
        if e.get("is_pack"):
            continue
        toks = name_tokens[e["id"]]
        if len(toks) < MIN_TOKENS:
            continue
        weighted = {t: weight(t) for t in toks}
        top = max(weighted, key=weighted.get)
        # every identifying word must be present, not just the rarest one.
        # ("Creme anti-taches Nuit Algovita" needs BOTH taches AND nuit.)
        required = {t for t, w in weighted.items() if w >= DISTINCTIVE} or {top}
        index.append({
            "id": e["id"],
            "name": e.get("name"),
            "weights": weighted,
            "total": sum(weighted.values()),
            "anchor": top,
            "anchor_w": weighted[top],
            "required": required,
        })
    index.sort(key=lambda x: -x["total"])

    packs = [e for e in enriched if e.get("is_pack")]
    print(f"{len(index)} matchable products | {len(packs)} packs\n")

    audit, total_hits, empty = [], 0, 0

    for p in packs:
        src = raw.get(p["id"], {})
        text = " ".join([src.get("name") or "",
                         src.get("short_desc") or "",
                         src.get("description") or ""])
        pack_toks = set(tokens(text))

        hits = []
        for c in index:
            if c["id"] == p["id"] or c["anchor_w"] < MIN_ANCHOR_W:
                continue
            # RULE 1: every identifying word must be there
            if not c["required"] <= pack_toks:
                continue
            # RULE 2: enough of the total evidence must be there
            got = sum(w for t, w in c["weights"].items() if t in pack_toks)
            mass = got / c["total"] if c["total"] else 0
            if mass >= MIN_MASS:
                hits.append({
                    "id": c["id"], "name": c["name"],
                    "mass": round(mass, 2),
                    "required": c["required"],
                })

        hits.sort(key=lambda h: -h["mass"])
        p["pack_contents_raw"] = [h["name"] for h in hits]
        p["pack_contents_ids"] = [h["id"] for h in hits]
        total_hits += len(hits)
        if not hits:
            empty += 1

        audit.append("\n" + "=" * 72)
        audit.append(f"PACK {p['id']}: {p.get('name')}")
        audit.append(f"  concerns: {', '.join(p.get('concerns') or []) or '-'}")
        audit.append(f"  skin:     {', '.join(p.get('skin_type') or []) or '-'}")
        if hits:
            for h in hits:
                audit.append(
                    f"  [{h['mass']}] {h['id']:>5}  {h['name']}"
                    f"   (required: {'+'.join(sorted(h['required']))})")
        else:
            audit.append("  NO COMPONENTS FOUND")
            audit.append(f"  text: {norm(text)[:220] or '(empty description)'}")

    with ENR_FILE.open("w", encoding="utf-8") as fh:
        for e in enriched:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    header = [
        "PACK COMPONENT RESOLUTION — AUDIT (v2, IDF-weighted)",
        "=" * 72,
        f"Packs processed:        {len(packs)}",
        f"Packs with components:  {len(packs) - empty}",
        f"Packs with none:        {empty}",
        f"Total components found: {total_hits}",
        "",
        "A product matches only if ALL of its identifying words (weight >= 3.0)",
        "appear in the pack text AND >= 72% of its evidence weight is present.",
        "",
        "Most generic words in the catalogue (down-weighted automatically):",
    ] + [f"   {t:<16} in {n:>3} names   weight {w}" for t, n, w in generic]

    AUDIT.write_text("\n".join(header + audit), encoding="utf-8")

    print(f"Packs with components:  {len(packs) - empty}/{len(packs)}")
    print(f"Total components found: {total_hits}")
    print("\nMost generic words (now carry little weight):")
    for t, n, w in generic[:6]:
        print(f"   {t:<16} in {n:>3} names   weight {w}")
    print(f"\nWrote {AUDIT}. Next: python3 finalize.py")


if __name__ == "__main__":
    main()
