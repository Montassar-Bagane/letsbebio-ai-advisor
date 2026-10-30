#!/usr/bin/env python3
"""
finalize.py — resolve pack contents to real product IDs, QA the extraction,
and write the final catalogue.

Input :  products_enriched.jsonl  (from enrich.py)
Output:  catalogue.json           (the deliverable)
         routines.json            (packs with resolved components)
         qa_report.txt            (coverage + problems to fix)

No dependencies beyond the standard library.

Run:
    python finalize.py
"""

import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

IN_FILE = Path("products_enriched.jsonl")
MATCH_THRESHOLD = 0.62      # below this, a pack component is left unresolved

STOPWORDS = {
    "le", "la", "les", "de", "du", "des", "et", "au", "aux", "un", "une",
    "pour", "avec", "sans", "bio", "naturel", "naturelle", "ml", "gr", "g",
    "kg", "pack", "duo", "trio", "coffret", "routine", "set", "lot",
}


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, drop stopwords."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t not in STOPWORDS and len(t) > 2]
    return " ".join(tokens)


def similarity(a: str, b: str) -> float:
    """Blend sequence ratio with token overlap — token overlap catches
    reordered names, sequence ratio catches near-identical strings."""
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return 0.4 * seq + 0.6 * jaccard


def main() -> None:
    if not IN_FILE.exists():
        raise SystemExit(f"{IN_FILE} not found — run enrich.py first.")

    products = [
        json.loads(line)
        for line in IN_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Loaded {len(products)} enriched products")

    # -- index for matching (exclude packs; a pack can't contain a pack) ------
    index = [
        (p["id"], p.get("name", ""), normalize(p.get("name", "")))
        for p in products
        if not p.get("is_pack")
    ]

    # -- resolve pack components --------------------------------------------
    routines, resolved_n, unresolved_n = [], 0, 0

    for p in products:
        if not p.get("is_pack"):
            continue

        components, unresolved = [], []
        for raw in p.get("pack_contents_raw", []):
            key = normalize(raw)
            best_id, best_name, best_score = None, None, 0.0
            for pid, name, norm in index:
                score = similarity(key, norm)
                if score > best_score:
                    best_id, best_name, best_score = pid, name, score

            if best_score >= MATCH_THRESHOLD:
                components.append({
                    "product_id": best_id,
                    "matched_name": best_name,
                    "raw_text": raw,
                    "match_score": round(best_score, 3),
                })
                resolved_n += 1
            else:
                unresolved.append(raw)
                unresolved_n += 1

        p["pack_contents"] = [c["product_id"] for c in components]
        routines.append({
            "pack_id": p["id"],
            "pack_name": p.get("name"),
            "brand": p.get("brand"),
            "price": p.get("price"),
            "skin_type": p.get("skin_type", []),
            "hair_type": p.get("hair_type", []),
            "concerns": p.get("concerns", []),
            "components": components,
            "unresolved": unresolved,
        })

    # -- QA ------------------------------------------------------------------
    lines = ["=" * 60, "EXTRACTION QA REPORT", "=" * 60, ""]
    lines.append(f"Products enriched:            {len(products)}")

    low = [p for p in products if (p.get("confidence") or 0) < 0.5]
    lines.append(f"Low confidence (<0.5):        {len(low)}")

    no_skin = [
        p for p in products
        if not p.get("skin_type")
        and p.get("routine_step") not in ("complement_oral", "non_applicable")
    ]
    lines.append(f"Topical products, no skin_type: {len(no_skin)}")

    no_conc = [p for p in products if not p.get("concerns")]
    lines.append(f"No concerns assigned:          {len(no_conc)}")

    lines += [
        "",
        f"Packs found:                  {len(routines)}",
        f"Components resolved:          {resolved_n}",
        f"Components unresolved:        {unresolved_n}",
        "",
    ]

    # -- vocabulary coverage -------------------------------------------------
    for field in ("product_format", "routine_step"):
        lines.append(f"--- {field} ---")
        for val, n in Counter(p.get(field) for p in products).most_common():
            lines.append(f"  {str(val):26} {n}")
        lines.append("")

    for field in ("skin_type", "hair_type", "concerns", "usage_time"):
        lines.append(f"--- {field} ---")
        counts = Counter(v for p in products for v in (p.get(field) or []))
        for val, n in counts.most_common():
            lines.append(f"  {val:26} {n}")
        lines.append("")

    # -- coverage against the beauty categories the client cares about -------
    lines.append("--- SKIN TYPE COVERAGE (products per type) ---")
    for st in ["normale", "seche", "mixte", "grasse", "sensible", "acneique", "mature"]:
        n = sum(1 for p in products if st in (p.get("skin_type") or []))
        flag = "  <-- THIN" if n < 5 else ""
        lines.append(f"  {st:26} {n}{flag}")
    lines.append("")

    lines.append("--- LOW CONFIDENCE PRODUCTS (review these) ---")
    for p in sorted(low, key=lambda x: x.get("confidence") or 0)[:30]:
        lines.append(f"  [{p['id']}] {(p.get('name') or '')[:60]}  conf={p.get('confidence')}")
    lines.append("")

    if unresolved_n:
        lines.append("--- UNRESOLVED PACK COMPONENTS (manual mapping needed) ---")
        for r in routines:
            for u in r["unresolved"]:
                lines.append(f"  pack {r['pack_id']}: {u[:70]}")

    Path("qa_report.txt").write_text("\n".join(lines), encoding="utf-8")
    Path("catalogue.json").write_text(
        json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("routines.json").write_text(
        json.dumps(routines, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n".join(lines[:24]))
    print("\nWrote catalogue.json, routines.json, qa_report.txt")


if __name__ == "__main__":
    main()
