#!/usr/bin/env python3
"""
2_extract.py — turn raw product text into structured attributes.

SINGLE SOURCE OF TRUTH
----------------------
The extraction rules live in ../service/app/extraction.py and are imported
here. They used to be duplicated, and the two copies drifted: fixes for food
classification and title-weighted concern ranking reached the service and never
reached the pipeline, so the same product could be classified two ways
depending on which script ran. Importing removes that possibility.

Input : products.jsonl          (produced by 1_export.sql)
Output: products_enriched.jsonl
        low_confidence_ids.txt  (products worth a manual look)

Usage:
    python3 2_extract.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

# --- import the rules from the service --------------------------------------
HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent / "service"
if not (SERVICE / "app" / "extraction.py").exists():
    sys.exit(f"Cannot find extraction rules at {SERVICE / 'app' / 'extraction.py'}")
sys.path.insert(0, str(SERVICE))

from app.extraction import extract          # noqa: E402

IN_FILE = Path("products.jsonl")
OUT_FILE = Path("products_enriched.jsonl")


def main() -> None:
    if not IN_FILE.exists():
        sys.exit(f"{IN_FILE} not found. Run 1_export.sql first:\n"
                 "  sudo mysql <db> --batch --raw --skip-column-names "
                 "< 1_export.sql > products.jsonl")

    rows, skipped = [], 0
    for line in IN_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1

    results = [extract(p) for p in rows]

    with OUT_FILE.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    unclear = [r for r in results if r["confidence"] < 0.5]
    autre = sum(1 for r in results if r["product_format"] == "autre")
    packs = sum(1 for r in results if r["is_pack"])
    topical = [r for r in results
               if r["routine_step"] not in ("complement_oral", "non_applicable")]
    with_skin = sum(1 for r in topical if r["skin_type"])

    print(f"Processed          {len(results)} products ({skipped} bad lines)")
    print(f"Unclassified       {autre}")
    print(f"Packs detected     {packs}")
    print(f"Topical products   {len(topical)}")
    print(f"  with skin_type   {with_skin}")
    print(f"Needs review       {len(unclear)}")

    zones = Counter(r.get("zone") for r in results)
    print("\nZones: " + ", ".join(f"{k}={v}" for k, v in zones.most_common()))

    print("\nTop concerns:")
    counts = Counter(c for r in results for c in r["concerns"])
    for name, n in counts.most_common(8):
        print(f"  {name:24} {n}")

    if unclear:
        Path("low_confidence_ids.txt").write_text(
            "\n".join(str(r["id"]) for r in unclear), encoding="utf-8")
        print(f"\nWrote low_confidence_ids.txt ({len(unclear)} products)")

    print(f"\nWrote {OUT_FILE}. Next: python3 3_resolve_packs.py")


if __name__ == "__main__":
    main()
