"""Semantic retrieval over the product catalogue.

Why this exists
---------------
The rule-based extraction matches vocabulary. Validation profile C02
("pellicules et cuir chevelu gras") returned zero products, even though the
catalogue contains a shampoo whose description speaks of "cuir chevelu irrité
et squames" — the same problem in different words. Keyword matching cannot
bridge that; embeddings can.

Design decisions worth defending
--------------------------------
1. NO VECTOR DATABASE. With ~600 products, cosine similarity over an in-memory
   matrix costs microseconds. Qdrant or Chroma would add an operational
   dependency for a client with no measurable benefit. Vector stores earn their
   place at a scale this catalogue is nowhere near.

2. RETRIEVAL WIDENS RECALL, RULES KEEP PRECISION. Semantic search proposes
   candidates; the deterministic engine still ranks them and still disqualifies
   products declaring an incompatible skin type. Embeddings never override a
   safety rule.

3. EMBEDDINGS ARE CACHED BY CONTENT HASH. Only products whose text changed are
   re-embedded on a rebuild, so a nightly refresh costs almost nothing.

4. THE WHOLE MODULE IS OPTIONAL. If no backend is configured or the import
   fails, `available()` returns False and every caller falls back to keyword
   search. The shop never breaks because an embedding model is missing.

Backends (set EMBED_BACKEND):
    local  — sentence-transformers, runs offline, free, no API key
    api    — any OpenAI-compatible /embeddings endpoint
    off    — disabled (default)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import unicodedata
from pathlib import Path

from . import derja
from .settings import settings

log = logging.getLogger("semantic")

_lock = threading.RLock()
_state = {
    "vectors": {},      # product id -> list[float], L2-normalised
    "hashes": {},       # product id -> hash of the embedded text
    "dim": 0,
    "built_at": None,
    "backend": None,
    "error": None,
    "warm": False,
}

# The cache is ~20 MB of JSON. Under WSL a project on /mnt/c is served through
# a Windows filesystem bridge, where reading it takes minutes rather than
# seconds — which is why the index appeared to hang. Default to the Linux
# filesystem and fall back to the working directory elsewhere.
def _default_cache() -> Path:
    cwd = str(Path.cwd())
    if cwd.startswith("/mnt/") and Path.home().exists():
        d = Path.home() / ".cache" / "reco-engine"
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d / "embeddings_cache.json"
        except OSError:
            pass
    return Path("embeddings_cache.json")


CACHE_FILE = Path(os.getenv("EMBED_CACHE", "")) if os.getenv("EMBED_CACHE") \
             else _default_cache()
BATCH = 64

# numpy makes the search ~50x faster but is not required
try:
    import numpy as _np
except ImportError:
    _np = None

_np_matrix = None      # (n, dim) normalised
_np_ids: list = []


# ---------------------------------------------------------------------------
# text preparation
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def product_text(p: dict) -> str:
    """What gets embedded.

    Title and short description carry most of the signal, so they come first;
    the long description is truncated because embedding models weight early
    tokens more heavily and the tail is usually boilerplate.
    """
    parts = [
        p.get("name") or "",
        p.get("brand") or "",
        p.get("categories") or "",
        _clean(p.get("short_desc") or p.get("benefit_summary") or "")[:400],
        _clean(p.get("description") or "")[:900],
    ]
    return " | ".join(x for x in parts if x)[:1600]


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------

_local_model = None


def _embed_local(texts: list) -> list:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        name = settings.EMBED_MODEL or "paraphrase-multilingual-MiniLM-L12-v2"
        log.info("loading local embedding model %s", name)
        _local_model = SentenceTransformer(name)
    out = _local_model.encode(texts, batch_size=32, show_progress_bar=False,
                              normalize_embeddings=True)
    return [list(map(float, v)) for v in out]


def _embed_api(texts: list) -> list:
    import urllib.request

    url = (settings.EMBED_BASE_URL or settings.LLM_BASE_URL).rstrip("/") \
          + "/embeddings"
    key = settings.EMBED_API_KEY or settings.LLM_API_KEY
    payload = json.dumps({
        "model": settings.EMBED_MODEL or "mistral-embed",
        "input": texts,
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"content-type": "application/json",
                 "accept": "application/json",
                 "user-agent": "reco-engine/1.0",
                 **({"authorization": "Bearer " + key} if key else {})},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)

    rows = sorted(data["data"], key=lambda d: d.get("index", 0))
    return [_normalise(r["embedding"]) for r in rows]


def _normalise(v: list) -> list:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _embed(texts: list) -> list:
    if settings.EMBED_BACKEND == "local":
        return _embed_local(texts)
    return _embed_api(texts)


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:                                  # corrupt cache
        log.warning("embedding cache unreadable, rebuilding: %s", e)
        return {}


def _save_cache(entries: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(entries), encoding="utf-8")
    except Exception as e:
        log.warning("could not write embedding cache: %s", e)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build(products: list) -> None:
    """Embed every product, reusing cached vectors for unchanged text."""
    if settings.EMBED_BACKEND not in ("local", "api"):
        return

    cache = _load_cache()
    vectors, hashes, pending, pending_ids = {}, {}, [], []

    for p in products:
        if p.get("is_pack"):
            continue                      # packs are matched through their parts
        pid = str(p["id"])
        text = product_text(p)
        h = _hash(text)
        hit = cache.get(pid)
        if hit and hit.get("h") == h:
            vectors[p["id"]] = hit["v"]
            hashes[p["id"]] = h
        else:
            pending.append(text)
            pending_ids.append((p["id"], h))

    if pending:
        log.info("embedding %d products (%d cached)", len(pending), len(vectors))
        try:
            for i in range(0, len(pending), BATCH):
                chunk = pending[i:i + BATCH]
                vecs = _embed(chunk)
                for (pid, h), v in zip(pending_ids[i:i + BATCH], vecs):
                    vectors[pid] = v
                    hashes[pid] = h
        except Exception as e:
            log.warning("embedding failed, semantic search disabled: %s", e)
            with _lock:
                _state["error"] = str(e)
            return

    dim = len(next(iter(vectors.values()))) if vectors else 0

    _save_cache({str(k): {"h": hashes[k], "v": vectors[k]} for k in vectors})

    global _np_matrix, _np_ids
    with _lock:
        _state.update({"vectors": vectors, "hashes": hashes, "dim": dim,
                       "backend": settings.EMBED_BACKEND, "error": None})
        if _np is not None and vectors:
            _np_ids = list(vectors.keys())
            _np_matrix = _np.array([vectors[i] for i in _np_ids],
                                   dtype=_np.float32)
        else:
            _np_ids, _np_matrix = [], None

    # Warm the query path. Building the index loads the model, but the first
    # single-sentence inference still pays a one-off cost for thread pools and
    # kernel selection — 20-30 s on a cold WSL. Paying it here means the first
    # customer query is fast instead of appearing to hang.
    try:
        _embed(["requete de prechauffage"])
        with _lock:
            _state["warm"] = True
        log.info("semantic index ready: %d vectors, dim %d (query path warm)",
                 len(vectors), dim)
    except Exception:
        log.info("semantic index ready: %d vectors, dim %d", len(vectors), dim)


def available() -> bool:
    with _lock:
        return bool(_state["vectors"])


def info() -> dict:
    with _lock:
        return {"enabled": bool(_state["vectors"]),
                "warm": _state["warm"],
                "cache": str(CACHE_FILE),
                "backend": _state["backend"],
                "vectors": len(_state["vectors"]),
                "dim": _state["dim"],
                "error": _state["error"]}


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def search(query: str, top_k: int = 8, allowed_ids: set | None = None,
           min_score: float | None = None) -> list:
    """Return [(product_id, similarity)] ordered by cosine similarity.

    `allowed_ids` lets a caller restrict retrieval to products that already
    satisfy a hard constraint — which is how semantic search is kept subordinate
    to the deterministic rules rather than able to bypass them.
    """
    # The floor is deliberately low. Cosine values are not comparable across
    # embedding models — a strongly relevant match scores ~0.6 with one model
    # and ~0.2 with another — so a high fixed threshold silently returns
    # nothing. Ranking does the real work; the floor only removes noise.
    if min_score is None:
        min_score = settings.EMBED_MIN_SCORE

    if not available() or not query or not query.strip():
        return []

    # Product descriptions are written in French. A Derja or Arabizi query
    # shares no tokens with them, so similarity collapses; appending the
    # recognised French equivalents gives the embedding something to match.
    enriched = derja.enrich_query(query.strip())

    try:
        qvec = _embed([enriched])[0]
    except Exception as e:
        log.warning("query embedding failed: %s", e)
        return []

    with _lock:
        vectors = _state["vectors"]
        matrix, ids = _np_matrix, _np_ids

    # numpy path
    if matrix is not None and _np is not None:
        sims = matrix @ _np.array(qvec, dtype=_np.float32)
        order = _np.argsort(-sims)
        out, best_allowed = [], None
        for idx in order:
            pid = ids[int(idx)]
            if allowed_ids is not None and pid not in allowed_ids:
                continue
            score = float(sims[int(idx)])
            if best_allowed is None:
                best_allowed = score
            if score < min_score:
                break
            out.append((pid, round(score, 4)))
            if len(out) >= top_k:
                break
        if not out and best_allowed is not None:
            log.info("no semantic hit above %.2f (best admissible was %.3f)",
                     min_score, best_allowed)
        return out

    # pure-python fallback: fine at this catalogue size
    scored = []
    for pid, vec in vectors.items():
        if allowed_ids is not None and pid not in allowed_ids:
            continue
        s = sum(a * b for a, b in zip(qvec, vec))
        if s >= min_score:
            scored.append((pid, round(s, 4)))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]
