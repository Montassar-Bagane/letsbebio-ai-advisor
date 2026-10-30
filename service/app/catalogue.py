"""Catalogue: reads the live WooCommerce database, runs extraction, caches
the result, and refreshes in the background.

Two speeds, on purpose:

  SLOW  full rebuild (descriptions -> structured fields). Product text changes
        rarely, so this runs on a timer, off the request path.
  FAST  price / stock for a handful of product ids. These change constantly,
        so they are read live for exactly the products being returned.

That combination is what stops a shopper ever seeing a stale price.
"""

from __future__ import annotations

import html
import logging
import math
import re
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone

import pymysql

from .settings import settings
from . import semantic
from .extraction import extract   # copied from enrich_rules.py

log = logging.getLogger("catalogue")

_lock = threading.RLock()
_state = {
    "products": [],        # enriched records
    "by_id": {},
    "packs": [],
    "built_at": None,
    "build_seconds": None,
    "error": None,
    "building": False,
}


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------

def _connect():
    kwargs = dict(
        user=settings.DB_USER, password=settings.DB_PASSWORD,
        database=settings.DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10, read_timeout=60,
    )
    if settings.DB_SOCKET:
        kwargs["unix_socket"] = settings.DB_SOCKET
    else:
        kwargs["host"] = settings.DB_HOST
        kwargs["port"] = settings.DB_PORT
    return pymysql.connect(**kwargs)


def _p(table: str) -> str:
    """Prefix a WordPress table name."""
    return f"`{settings.WP_PREFIX}{table}`"


PRODUCT_SQL = f"""
SELECT p.ID                AS id,
       p.post_title        AS name,
       p.post_name         AS slug,
       p.post_excerpt      AS short_desc,
       LEFT(p.post_content, 4000) AS description,
       (SELECT meta_value FROM {_p('postmeta')}
         WHERE post_id = p.ID AND meta_key = '_price' LIMIT 1)            AS price,
       (SELECT meta_value FROM {_p('postmeta')}
         WHERE post_id = p.ID AND meta_key = '_regular_price' LIMIT 1)    AS regular_price,
       (SELECT meta_value FROM {_p('postmeta')}
         WHERE post_id = p.ID AND meta_key = '_stock' LIMIT 1)            AS stock,
       (SELECT meta_value FROM {_p('postmeta')}
         WHERE post_id = p.ID AND meta_key = '_stock_status' LIMIT 1)     AS stock_status,
       (SELECT meta_value FROM {_p('postmeta')}
         WHERE post_id = p.ID AND meta_key = 'total_sales' LIMIT 1)       AS total_sales,
       (SELECT meta_value FROM {_p('postmeta')}
         WHERE post_id = p.ID AND meta_key = '_wc_average_rating' LIMIT 1) AS rating,
       (SELECT meta_value FROM {_p('postmeta')}
         WHERE post_id = p.ID AND meta_key = '_thumbnail_id' LIMIT 1)     AS image_id,
       (SELECT GROUP_CONCAT(t.name SEPARATOR ', ')
          FROM {_p('term_relationships')} tr
          JOIN {_p('term_taxonomy')} tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
          JOIN {_p('terms')} t ON t.term_id = tt.term_id
         WHERE tr.object_id = p.ID AND tt.taxonomy = 'product_brand')     AS brand,
       (SELECT GROUP_CONCAT(t.name SEPARATOR ', ')
          FROM {_p('term_relationships')} tr
          JOIN {_p('term_taxonomy')} tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
          JOIN {_p('terms')} t ON t.term_id = tt.term_id
         WHERE tr.object_id = p.ID AND tt.taxonomy = 'product_cat'
           AND t.slug NOT IN %(excluded)s)                                AS categories
FROM {_p('posts')} p
WHERE p.post_type = 'product'
  AND p.post_status = 'publish'
  AND (p.post_content <> '' OR p.post_excerpt <> ''
       OR p.post_title REGEXP '(^| )(Pack|Duo|Trio|Coffret|Routine|Kit|Set|Lot)')
"""

IMAGE_SQL = f"""
SELECT post_id AS id, meta_value AS path
FROM {_p('postmeta')}
WHERE meta_key = '_wp_attached_file' AND post_id IN %(ids)s
"""

LIVE_SQL = f"""
SELECT post_id AS id, meta_key, meta_value
FROM {_p('postmeta')}
WHERE meta_key IN ('_price','_regular_price','_sale_price','_stock','_stock_status')
  AND post_id IN %(ids)s
"""


def fetch_live(ids: list) -> dict:
    """Current price and stock for specific products. Small, fast, per-request."""
    if not ids or not settings.LIVE_STOCK:
        return {}
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(LIVE_SQL, {"ids": tuple(ids)})
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:                       # never break a response on this
        log.warning("live price/stock lookup failed: %s", e)
        return {}

    out = {}
    for r in rows:
        out.setdefault(r["id"], {})[r["meta_key"].lstrip("_")] = r["meta_value"]
    return out


# ---------------------------------------------------------------------------
# pack composition (IDF-weighted containment; see resolve_packs.py)
# ---------------------------------------------------------------------------

STOP = {
    "le","la","les","de","du","des","et","au","aux","un","une","en","pour","avec",
    "sans","sur","par","dans","ou","a","l","d","se","bio","naturel","naturelle",
    "naturels","biologique","pur","pure","ml","cl","gr","g","kg","gelules","gelule",
    "comprimes","comprime","capsules","sachets","sachet","flacon","pot","tube",
    "boite","pack","duo","trio","coffret","routine","kit","set","lot","produit",
    "produits","soin","soins","nouveau","promo","offre",
}
MIN_MASS, DISTINCTIVE = 0.72, 3.0


def _norm(t: str) -> str:
    if not t:
        return ""
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _toks(t: str) -> list:
    return [x for x in _norm(t).split() if x not in STOP and len(x) > 2]


def _resolve_packs(enriched: list, raw_by_id: dict) -> None:
    name_toks = {e["id"]: set(_toks(e.get("name") or "")) for e in enriched}
    n = len(name_toks) or 1
    df = Counter()
    for s in name_toks.values():
        df.update(s)

    def w(tok):
        return math.log(n / (1 + df[tok]))

    index = []
    for e in enriched:
        if e.get("is_pack"):
            continue
        toks = name_toks[e["id"]]
        if len(toks) < 2:
            continue
        weights = {t: w(t) for t in toks}
        top = max(weights, key=weights.get)
        required = {t for t, val in weights.items() if val >= DISTINCTIVE} or {top}
        index.append({"id": e["id"], "name": e.get("name"), "weights": weights,
                      "total": sum(weights.values()), "required": required,
                      "top_w": weights[top]})

    for e in enriched:
        if not e.get("is_pack"):
            continue
        src = raw_by_id.get(e["id"], {})
        text = " ".join([src.get("name") or "", src.get("short_desc") or "",
                         src.get("description") or ""])
        pt = set(_toks(text))
        hits = []
        for c in index:
            if c["id"] == e["id"] or c["top_w"] < 1.5:
                continue
            if not c["required"] <= pt:
                continue
            got = sum(v for t, v in c["weights"].items() if t in pt)
            if c["total"] and got / c["total"] >= MIN_MASS:
                hits.append((got / c["total"], c["id"], c["name"]))
        hits.sort(reverse=True)
        e["pack_contents_ids"] = [h[1] for h in hits]
        e["pack_contents_raw"] = [h[2] for h in hits]


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build() -> dict:
    """Full rebuild from the live database. Safe to call concurrently:
    the swap at the end is atomic and readers never see a half-built list."""
    t0 = time.time()
    excluded = tuple(settings.EXCLUDED_CATEGORY_SLUGS) or ("__none__",)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(PRODUCT_SQL, {"excluded": excluded})
            raw = cur.fetchall()
            ids = [r["id"] for r in raw]
            images = {}
            if ids:
                for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
                    cur.execute(IMAGE_SQL, {"ids": tuple(chunk)})
                    for row in cur.fetchall():
                        images[row["id"]] = row["path"]
    finally:
        conn.close()

    enriched = []
    for r in raw:
        rec = extract(r)
        img = images.get(int(r["image_id"])) if r.get("image_id") else None
        rec["image_url"] = (f"{settings.SITE_URL}/wp-content/uploads/{img}"
                            if img and settings.SITE_URL else None)
        rec["url"] = (f"{settings.SITE_URL}/?p={r['id']}"
                      if settings.SITE_URL else None)
        enriched.append(rec)

    _resolve_packs(enriched, {r["id"]: r for r in raw})

    snapshot = {
        "products": enriched,
        "by_id": {e["id"]: e for e in enriched},
        "packs": [e for e in enriched if e.get("is_pack")],
        "built_at": datetime.now(timezone.utc).isoformat(),
        "build_seconds": round(time.time() - t0, 2),
        "error": None,
        "building": False,
    }
    with _lock:
        _state.update(snapshot)
    log.info("catalogue rebuilt: %d products in %.2fs",
             len(enriched), snapshot["build_seconds"])

    # The semantic index is rebuilt after the catalogue, never before: a
    # failure here must not prevent the catalogue itself from serving.
    try:
        semantic.build(enriched)
    except Exception:
        log.exception("semantic index build failed; keyword search still works")

    return snapshot


def get():
    with _lock:
        return dict(_state)


def ready() -> bool:
    with _lock:
        return bool(_state["products"])


def _loop():
    while True:
        try:
            with _lock:
                _state["building"] = True
            build()
        except Exception as e:                    # keep serving the old snapshot
            log.exception("rebuild failed")
            with _lock:
                _state["error"] = str(e)
                _state["building"] = False
        time.sleep(max(60, settings.REBUILD_MINUTES * 60))


def start_background_refresh():
    threading.Thread(target=_loop, daemon=True, name="catalogue-refresh").start()
