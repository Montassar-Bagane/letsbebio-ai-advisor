"""Deterministic scoring and routine assembly.

No model runs here, by design. Every number below is a product decision
somebody can inspect and argue with, and the same input always produces the
same output. That is what makes a recommendation defensible to a client.
"""

from __future__ import annotations

import math

SKIN_CONCERNS = ["taches_pigmentaires", "rides_age", "deshydratation",
                 "imperfections_acne", "rougeurs_sensibilite", "exces_sebum",
                 "eclat_teint", "protection_solaire", "cernes_poches",
                 "pores_dilates", "hygiene"]
HAIR_CONCERNS = ["chute_cheveux", "pellicules", "cheveux_abimes",
                 "deshydratation", "exces_sebum", "rougeurs_sensibilite"]
ORAL_CONCERNS = ["digestion", "immunite", "sommeil_stress", "energie_tonus",
                 "articulations", "memoire_concentration", "glycemie_tension",
                 "fertilite", "sport_nutrition", "cheveux_peau_ongles",
                 "minceur_detox"]

DOMAINS = {
    "visage": {
        "formats": {"nettoyant", "demaquillant", "lotion_tonique", "serum",
                    "creme_hydratante", "masque", "gommage", "contour_yeux",
                    "solaire", "huile_visage", "argile", "hydrolat", "savon"},
        "zones": {"visage", "yeux", "levres", "polyvalent"},
        "primary_zone": "visage", "type": "skin", "concerns": SKIN_CONCERNS},
    "cheveux": {
        "formats": {"shampooing", "apres_shampooing", "huile_capillaire",
                    "coloration_vegetale", "masque", "huile_vegetale", "argile"},
        "zones": {"cheveux", "polyvalent"},
        "primary_zone": "cheveux", "type": "hair", "concerns": HAIR_CONCERNS},
    "corps": {
        "formats": {"lait_corps", "deodorant", "bain", "savon", "huile_vegetale",
                    "gommage", "dentifrice", "huile_essentielle"},
        "zones": {"corps", "mains", "pieds", "bouche", "polyvalent"},
        "primary_zone": "corps", "type": "skin", "concerns": SKIN_CONCERNS},
    "interieur": {
        "formats": {"complement_gelules", "complement_poudre", "tisane"},
        "zones": {"oral", "polyvalent"},
        "primary_zone": "oral", "type": None, "concerns": ORAL_CONCERNS},
}

STEP_ORDER = ["nettoyage", "tonification", "traitement", "hydratation",
              "protection", "soin_cible"]

# Supplements are not a topical sequence — there is no "cleanse then moisturise"
# for a capsule. A cure is a small set of complementary products taken together,
# so it is built by variety of format rather than by step order.
ORAL_STEPS = ["complement_oral"]
MAX_CURE = 2

REASON = {
    "primary": "cible en priorité",
    "secondary": "traite aussi",
}

# Concerns that must not be answered with each other's products.
# Someone reporting bloating asked about digestion, not weight loss: offering
# slimming products is both a category error and a nudge they did not ask for.
# Keys are what the shopper asked for; values are what must not lead.
CONFLICTS = {
    "digestion": {"minceur_detox"},
    "immunite": {"minceur_detox"},
    "sommeil_stress": {"minceur_detox", "energie_tonus"},
    "energie_tonus": {"minceur_detox", "sommeil_stress"},
    "articulations": {"minceur_detox"},
    "cheveux_peau_ongles": {"minceur_detox"},
}


def in_domain(p: dict, domain: str) -> bool:
    d = DOMAINS[domain]
    if p.get("product_format") not in d["formats"]:
        return False
    z = p.get("zone")
    if z and z not in d["zones"]:
        return False
    return True


def score_product(p: dict, req) -> dict | None:
    """Return {'score', 'reason', 'match'} or None if the product does not
    qualify. Returning None rather than a low score matters: a contraindicated
    product must never appear, however good its rating."""
    d = DOMAINS[req.domain]
    type_key = "hair_type" if d["type"] == "hair" else "skin_type"

    # --- concern: the primary axis ---------------------------------------
    concerns = p.get("concerns") or []
    idx = -1
    for c in req.concerns:
        i = concerns.index(c) if c in concerns else -1
        if i != -1 and (idx == -1 or i < idx):
            idx = i
    if idx == -1:
        return None

    # a product whose main purpose conflicts with the request must not lead
    primary_concern = concerns[0] if concerns else None
    for asked in req.concerns:
        banned = CONFLICTS.get(asked, set())
        if primary_concern in banned and asked not in banned:
            return None

    s = 15.0 if idx == 0 else max(15.0 - idx * 2.5, 4.0)
    match = {"concern": "primary" if idx == 0 else "secondary"}
    reason = REASON[match["concern"]]

    # --- skin / hair type: refines, and can disqualify --------------------
    if req.skin_type and d["type"]:
        t = p.get(type_key) or []
        if req.skin_type in t:
            s += 9
            match["skin_type"] = "explicit"
        elif "tous" in t:
            s += 3
            match["skin_type"] = "all_types"
        elif t:
            return None                     # contraindicated
        else:
            match["skin_type"] = "unstated"

    # --- zone: a lip scrub must not open a facial routine -----------------
    z = p.get("zone")
    if z and z != "polyvalent":
        s += 5 if z == d["primary_zone"] else -4

    # --- time of day ------------------------------------------------------
    if req.usage_time:
        u = p.get("usage_time") or []
        if req.usage_time in u:
            s += 4
        elif "indifferent" not in u:
            s -= 3

    # --- commercial signals, deliberately weak ----------------------------
    try:
        r = float(p.get("rating") or 0)
        if r > 0:
            s += r * 1.1
    except (TypeError, ValueError):
        pass
    try:
        sales = float(p.get("total_sales") or 0)
        if sales > 0:
            s += math.log(1 + sales) * 0.7
    except (TypeError, ValueError):
        pass

    # trust thin extractions less
    s *= 0.6 + 0.4 * float(p.get("confidence") or 0.6)

    if (p.get("stock_status") or "instock") != "instock":
        s -= 6

    return {"score": round(s, 2), "reason": reason, "match": match}


def candidates(products: list, req) -> list:
    out = []
    for p in products:
        if p.get("is_pack") or not in_domain(p, req.domain):
            continue
        if req.brand and (p.get("brand") or "") != req.brand:
            continue
        if req.in_stock_only and (p.get("stock_status") or "instock") != "instock":
            continue
        if req.budget_max:
            try:
                price = float(p.get("price") or 0)
            except (TypeError, ValueError):
                price = 0
            if price and price > req.budget_max:
                continue
        sc = score_product(p, req)
        if not sc:
            continue
        out.append((sc, p))
    out.sort(key=lambda x: -x[0]["score"])
    return out


def build_routine(scored: list, domain: str = "visage") -> list:
    """Topical domains: the best product at each step, in application order.
    Oral domain: a short cure of complementary supplements."""
    if domain == "interieur":
        return _build_cure(scored)

    used, steps = set(), []
    for step in STEP_ORDER:
        for sc, p in scored:
            if p.get("routine_step") == step and p["id"] not in used:
                used.add(p["id"])
                steps.append((step, sc, p))
                break
    return steps


def _build_cure(scored: list) -> list:
    """Top supplements, preferring a mix of formats (gélules + tisane + poudre)
    over three versions of the same thing."""
    picked, seen_fmt, used = [], set(), set()

    for sc, p in scored:                       # first pass: one per format
        fmt = p.get("product_format")
        if fmt in seen_fmt or p["id"] in used:
            continue
        seen_fmt.add(fmt)
        used.add(p["id"])
        picked.append(("complement_oral", sc, p))
        if len(picked) >= MAX_CURE:
            return picked

    for sc, p in scored:                       # top up if formats were few
        if p["id"] in used:
            continue
        used.add(p["id"])
        picked.append(("complement_oral", sc, p))
        if len(picked) >= MAX_CURE:
            break
    return picked


def matching_packs(packs: list, req, limit: int = 4) -> list:
    out = []
    for r in packs:
        rc = set(r.get("concerns") or [])
        if not rc & set(req.concerns):
            continue
        st = r.get("skin_type") or []
        if req.skin_type and st and req.skin_type not in st:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out
