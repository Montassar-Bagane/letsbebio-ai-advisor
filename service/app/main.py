"""Recommendation API.

    GET  /health              liveness + catalogue freshness
    GET  /options             questionnaire choices, built from live data
    POST /recommend           the engine
    POST /interpret           free text -> profile (optional, LLM)
    POST /admin/refresh       force a rebuild (token required)
"""

from __future__ import annotations

import logging

log = logging.getLogger("main")
import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import agent, catalogue, derja, scoring, semantic
from .settings import settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")

app = FastAPI(title=f"Recommendation API — {settings.CLIENT_NAME}",
              version="1.0.0", docs_url="/docs")

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def _startup():
    catalogue.start_background_refresh()


# ---------------------------------------------------------------------------
# rate limiting — in-memory, per IP. Enough for a single instance; move to
# Redis if this is ever load-balanced across processes.
# ---------------------------------------------------------------------------

_hits: dict = defaultdict(deque)


async def rate_limit(request: Request):
    if settings.RATE_LIMIT_PER_MIN <= 0:
        return
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= settings.RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Trop de requêtes, réessayez dans un instant.")
    q.append(now)


def require_admin(x_admin_token: str = Header(default="")):
    if not settings.ADMIN_TOKEN or x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------

Domain = Literal["visage", "cheveux", "corps", "interieur"]


class RecommendRequest(BaseModel):
    domain: Domain = "visage"
    concerns: list[str] = Field(default_factory=list, max_length=3)
    skin_type: str | None = None
    usage_time: Literal["matin", "soir"] | None = None
    budget_max: float | None = Field(default=None, ge=0)
    brand: str | None = None
    in_stock_only: bool = True
    limit_alternatives: int = Field(default=12, ge=0, le=40)


class InterpretRequest(BaseModel):
    text: str = Field(min_length=3, max_length=1000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    domain: Domain | None = None
    skin_type: str | None = None
    limit: int = Field(default=8, ge=1, le=20)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _money(v):
    """Tunisian dinars carry 3 decimals (millimes). WooCommerce float artifacts
    like 45.378151 are display noise, not precision."""
    if v in (None, ""):
        return None
    try:
        return f"{round(float(v), 3):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return v


def _public(p: dict, live: dict) -> dict:
    """Product as the storefront sees it, with live price and stock merged in."""
    lv = live.get(p["id"], {})
    price = lv.get("price", p.get("price"))
    status = lv.get("stock_status", p.get("stock_status")) or "instock"
    return {
        "id": p["id"],
        "name": p.get("name"),
        "brand": p.get("brand"),
        "price": _money(price),
        "regular_price": _money(lv.get("regular_price", p.get("regular_price"))),
        "in_stock": status == "instock",
        "stock": lv.get("stock", p.get("stock")),
        "format": p.get("product_format"),
        "zone": p.get("zone"),
        "skin_type": p.get("skin_type") or [],
        "hair_type": p.get("hair_type") or [],
        "concerns": p.get("concerns") or [],
        "usage_time": p.get("usage_time") or [],
        "volume_size": p.get("volume_size"),
        "summary": p.get("benefit_summary"),
        "image_url": p.get("image_url"),
        "url": p.get("url"),
    }


def _require_ready():
    if not catalogue.ready():
        raise HTTPException(503, "Catalogue en cours de chargement, réessayez.")


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    st = catalogue.get()
    return {
        "status": "ok" if st["products"] else "starting",
        "client": settings.CLIENT_NAME,
        "products": len(st["products"]),
        "packs": len(st["packs"]),
        "built_at": st["built_at"],
        "build_seconds": st["build_seconds"],
        "rebuilding": st["building"],
        "last_error": st["error"],
        "live_stock": settings.LIVE_STOCK,
        "semantic": semantic.info(),
    }


@app.get("/options", dependencies=[Depends(rate_limit)])
def options(domain: Domain = "visage"):
    """Questionnaire choices, derived from the catalogue so the interface can
    never offer a filter with nothing behind it."""
    _require_ready()
    st = catalogue.get()
    d = scoring.DOMAINS[domain]
    allow = set(d["concerns"])
    type_key = "hair_type" if d["type"] == "hair" else "skin_type"

    concerns, types, brands = {}, {}, {}
    for p in st["products"]:
        if p.get("is_pack") or not scoring.in_domain(p, domain):
            continue
        for c in p.get("concerns") or []:
            if c in allow:
                concerns[c] = concerns.get(c, 0) + 1
        if d["type"]:
            for t in p.get(type_key) or []:
                if t != "tous":
                    types[t] = types.get(t, 0) + 1
        if p.get("brand"):
            brands[p["brand"]] = brands.get(p["brand"], 0) + 1

    srt = lambda m, mn=1: [{"value": k, "count": v} for k, v in
                           sorted(m.items(), key=lambda x: -x[1]) if v >= mn]
    return {"domain": domain,
            "concerns": srt(concerns, 3),
            "types": srt(types),
            "type_kind": d["type"],
            "brands": srt(brands)}


@app.post("/recommend", dependencies=[Depends(rate_limit)])
def recommend(req: RecommendRequest):
    _require_ready()
    st = catalogue.get()

    valid = set(scoring.DOMAINS[req.domain]["concerns"])
    req.concerns = [c for c in req.concerns if c in valid]
    if not req.concerns:
        raise HTTPException(422, "Aucune préoccupation valide pour ce domaine.")

    scored = scoring.candidates(st["products"], req)
    steps = scoring.build_routine(scored, req.domain)
    packs = scoring.matching_packs(st["packs"], req)

    in_routine = {p["id"] for _, _, p in steps}
    alts = [(sc, p) for sc, p in scored if p["id"] not in in_routine
            ][: req.limit_alternatives]

    ids = list(in_routine) + [p["id"] for _, p in alts]
    for r in packs:
        ids.append(r["id"])
        ids.extend(r.get("pack_contents_ids") or [])
    live = catalogue.fetch_live(list(dict.fromkeys(ids)))

    return {
        "profile": {
            "domain": req.domain,
            "concerns": req.concerns,
            "skin_type": req.skin_type,
            "usage_time": req.usage_time,
            "matched_products": len(scored),
        },
        "routine": [
            {"step": step, "position": i + 1,
             "product": _public(p, live),
             "reason": sc["reason"], "match": sc["match"], "score": sc["score"]}
            for i, (step, sc, p) in enumerate(steps)
        ],
        "packs": [
            {"id": r["id"], "name": r.get("name"), "brand": r.get("brand"),
             "price": _money(live.get(r["id"], {}).get("price", r.get("price"))),
             "url": r.get("url"),
             "components": [_public(st["by_id"][cid], live)
                            for cid in (r.get("pack_contents_ids") or [])
                            if cid in st["by_id"]],
             "components_known": bool(r.get("pack_contents_ids"))}
            for r in packs
        ],
        "alternatives": [
            {"product": _public(p, live), "reason": sc["reason"],
             "match": sc["match"], "score": sc["score"]}
            for sc, p in alts
        ],
        "meta": {"engine": "rules_v2",
                 "catalogue_built_at": st["built_at"],
                 "live_pricing": settings.LIVE_STOCK},
    }


@app.post("/interpret", dependencies=[Depends(rate_limit)])
def interpret(req: InterpretRequest):
    """Free text -> a RecommendRequest body.

    The model interprets the question. It never chooses products: the caller
    passes the result to /recommend, and the interface shows the interpreted
    profile so the shopper can correct it.

    Works with any OpenAI-compatible endpoint (Groq, Mistral, Gemini, Ollama).
    Every value the model returns is checked against the fixed vocabularies
    below, so a hallucinated concern is discarded rather than reaching the
    engine.
    """
    if not settings.ENABLE_INTERPRET:
        # The Derja mapping is deterministic, so a request in Derja still
        # resolves to a usable profile when no language model is configured.
        d = derja.analyse(req.text)
        if d["concerns"]:
            dom = d["domain"] or "visage"
            allowed = set(scoring.DOMAINS[dom]["concerns"])
            return {"domain": dom,
                    "concerns": [c for c in d["concerns"] if c in allowed][:3],
                    "skin_type": d["skin_type"],
                    "usage_time": None, "budget_max": None,
                    "in_stock_only": True,
                    "understood": True,
                    "method": "rules_derja",
                    "_source_text": req.text}
        raise HTTPException(503, "Interprétation de texte libre désactivée.")

    import json
    import urllib.error
    import urllib.request

    SKIN = ["normale", "seche", "mixte", "grasse", "sensible", "acneique", "mature"]
    all_concerns = sorted({c for d in scoring.DOMAINS.values() for c in d["concerns"]})

    d = derja.analyse(req.text)
    hint = ""
    if d["is_derja"] and (d["concerns"] or d["domain"]):
        hint = ("\nLecture automatique (derja): "
                + f"domaine={d['domain']}, type_peau={d['skin_type']}, "
                + f"preoccupations={d['concerns']}. Verifie et complete.")

    system = (
        "Tu convertis la demande d'un client de cosmétiques et produits naturels "
        "en profil structuré.\n"
        "Réponds UNIQUEMENT en JSON, sans texte autour ni balises Markdown.\n"
        "Clés attendues : domain, concerns (1 à 3), skin_type, usage_time, budget_max.\n"
        f"domain doit valoir l'une de : {list(scoring.DOMAINS)}\n"
        f"concerns doivent venir de : {all_concerns}\n"
        f"skin_type doit valoir l'une de : {SKIN} ou null\n"
        "usage_time : matin, soir ou null. budget_max : nombre ou null.\n"
        "N'invente aucune valeur hors de ces listes. Si l'information est "
        "absente, mets null. Le visage est le domaine par défaut.\n"
        + derja.prompt_guidance(d["script"]) + hint
    )

    payload = json.dumps({
        "model": settings.LLM_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": req.text}],
        "temperature": 0,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }).encode()

    # A real User-Agent is required: the default "Python-urllib/x.y" is
    # rejected outright (403) by the edge protection in front of several
    # providers, before the request ever reaches the model.
    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": "reco-engine/1.0 (+https://claude.com)",
    }
    if settings.LLM_API_KEY:
        headers["authorization"] = "Bearer " + settings.LLM_API_KEY

    try:
        r = urllib.request.Request(
            settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
            data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(r, timeout=settings.LLM_TIMEOUT) as resp:
            raw = json.load(resp)
        text = raw["choices"][0]["message"]["content"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
        data = json.loads(text)
    except urllib.error.HTTPError as e:
        # include the provider's own message: "model not found", "quota
        # exceeded" and "blocked" are very different problems
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = ""
        log.warning("interpret failed: HTTP %s %s | %s", e.code, e.reason, detail)
        raise HTTPException(502, "Interprétation indisponible.")
    except Exception as e:
        log.warning("interpret failed: %s: %s", type(e).__name__, e)
        raise HTTPException(502, "Interprétation indisponible.")

    # --- validate everything the model returned ---------------------------
    domain = data.get("domain") if data.get("domain") in scoring.DOMAINS else "visage"
    allowed = set(scoring.DOMAINS[domain]["concerns"])
    concerns = [c for c in (data.get("concerns") or []) if c in allowed][:3]

    if not concerns:                       # fall back rather than fail
        for d, cfg in scoring.DOMAINS.items():
            hit = [c for c in (data.get("concerns") or []) if c in cfg["concerns"]]
            if hit:
                domain, concerns = d, hit[:3]
                break

    budget = data.get("budget_max")
    try:
        budget = float(budget) if budget else None
    except (TypeError, ValueError):
        budget = None

    return {
        "domain": domain,
        "concerns": concerns,
        "skin_type": data.get("skin_type") if data.get("skin_type") in SKIN else None,
        "usage_time": data.get("usage_time") if data.get("usage_time") in ("matin", "soir") else None,
        "budget_max": budget,
        "in_stock_only": True,
        "understood": bool(concerns),
        "_source_text": req.text,
    }


@app.post("/search", dependencies=[Depends(rate_limit)])
def search(req: SearchRequest):
    """Retrieval by meaning.

    Complements /recommend rather than replacing it: keyword extraction is
    precise but brittle, embeddings are tolerant but unranked. Candidates are
    restricted to products the deterministic rules already admit, so semantic
    similarity can widen recall without weakening the suitability constraints.
    """
    _require_ready()
    if not semantic.available():
        raise HTTPException(503, "Recherche semantique desactivee.")

    st = catalogue.get()
    allowed = None
    if req.domain:
        d = scoring.DOMAINS[req.domain]
        key = "hair_type" if d["type"] == "hair" else "skin_type"
        allowed = set()
        for p in st["products"]:
            if p.get("is_pack") or not scoring.in_domain(p, req.domain):
                continue
            declared = p.get(key) or []
            if (req.skin_type and d["type"] and declared
                    and req.skin_type not in declared and "tous" not in declared):
                continue
            allowed.add(p["id"])

    hits = semantic.search(req.query, top_k=req.limit, allowed_ids=allowed)
    live = catalogue.fetch_live([pid for pid, _ in hits])

    return {
        "query": req.query,
        "results": [
            {"product": _public(st["by_id"][pid], live),
             "similarity": score}
            for pid, score in hits if pid in st["by_id"]
        ],
        "meta": {"method": "semantic",
                 "min_score": settings.EMBED_MIN_SCORE,
                 "candidates": len(allowed) if allowed is not None else None,
                 **semantic.info()},
    }


@app.post("/chat", dependencies=[Depends(rate_limit)])
def chat(req: ChatRequest):
    """Conversational advisor.

    Unlike /recommend, this runs a tool-calling loop: the model chooses what
    to look up next based on what the last call returned. That is what makes
    it an agent rather than a pipeline.

    The products in the response come from tool results only — never from the
    model's prose — so the interface cannot render something that does not
    exist in the catalogue.
    """
    if not settings.ENABLE_INTERPRET:
        raise HTTPException(503, "Conseiller conversationnel désactivé.")
    _require_ready()

    try:
        out = agent.run([t.model_dump() for t in req.history], req.message)
    except RuntimeError as e:
        reason = str(e)
        if reason == "llm_model_not_found":
            raise HTTPException(502, "Le modèle configuré n'existe plus "
                                     "(make models, puis make set-model).")
        if reason == "llm_bad_key":
            raise HTTPException(502, "Clé API refusée par le fournisseur.")
        if reason == "llm_no_tools":
            raise HTTPException(502, "Ce modèle ne gère pas les outils "
                                     "(make models, choisir un modèle [tools]).")
        log.error("agent RuntimeError: %s", reason)
        raise HTTPException(502, "Conseiller momentanément indisponible.")
    except Exception as e:
        log.exception("agent unexpected error: %s", e)
        raise HTTPException(502, "Conseiller momentanément indisponible.")

    ids = [p["id"] for p in out["produits"]]
    live = catalogue.fetch_live(ids)
    st = catalogue.get()
    cards = [_public(st["by_id"][i], live) for i in ids if i in st["by_id"]]

    return {
        "reply": out["reply"],
        "products": cards,
        "routine": [{"step": p.get("etape_routine"), "product_id": p["id"],
                     "reason": p.get("raison")} for p in out["routine"]],
        "followup_questions": out.get("followup_questions", []),
        "history": out["history"],
        "meta": {"tool_calls": out["etapes_outils"], "engine": "agent_v1"},
    }


class SyncRequest(BaseModel):
    products: list[dict]
    site_url: str | None = None
    admin_token: str | None = None


@app.post("/sync")
def sync(req: SyncRequest):
    """Direct push catalogue synchronization from WordPress.
    
    Allows zero-configuration deployment without opening MySQL port 3306
    or configuring database credentials in the environment.
    """
    if settings.ADMIN_TOKEN and req.admin_token and req.admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(403, "Token invalide")
    if not req.products:
        raise HTTPException(400, "Aucun produit fourni")

    st = catalogue.load_from_raw(req.products, req.site_url or "")
    return {
        "status": "ok",
        "synced": len(st["products"]),
        "packs": len(st["packs"]),
        "seconds": st["build_seconds"],
        "built_at": st["built_at"],
    }


@app.post("/admin/refresh", dependencies=[Depends(require_admin)])
def refresh():
    st = catalogue.build()
    return {"rebuilt": True, "products": len(st["products"]),
            "seconds": st["build_seconds"], "built_at": st["built_at"]}
