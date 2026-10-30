#!/usr/bin/env python3
"""
enrich_rules.py  v2 — rule-based extraction. No API key, no cost.

CHANGES FROM v1
  1. Food/grocery patterns added -> the 110 products stuck in "autre" now
     resolve to aliment / epice / huile_alimentaire / boisson.
  2. Concerns are now WEIGHTED. v1 fired "deshydratation" on 109 products
     because the word "hydratant" appears in nearly every cosmetic text.
     Now a concern needs one STRONG signal, or two WEAK ones.
  3. Confidence rewritten. v1 marked correctly-identified food as low
     confidence. A bag of lentils with no skin type is a CORRECT result,
     not an uncertain one. Confidence now measures "did we understand this
     product", not "did we find skin data".

Input :  products.jsonl
Output:  products_enriched.jsonl
         low_confidence_ids.txt   (only genuinely unclear products)

Run:  python3 enrich_rules.py
"""

import html
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

IN_FILE = Path("products.jsonl")
OUT_FILE = Path("products_enriched.jsonl")


def norm(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# SKIN / HAIR
# ---------------------------------------------------------------------------

SKIN = {
    "normale":  [r"peaux? normales?"],
    "seche":    [r"peaux? (?:tres )?seches?", r"normale?-seche", r"normales? a seches?"],
    "mixte":    [r"peaux? mixtes?"],
    "grasse":   [r"peaux? grasses?", r"mixtes? a grasses?", r"seboregulateur",
                 r"peaux? a tendance grasse"],
    "sensible": [r"peaux? sensibles?", r"peaux? reactives?", r"peaux? fragiles?",
                 r"peaux? intolerantes?"],
    "acneique": [r"acnei?que", r"peaux? a imperfections", r"anti-?acne"],
    "mature":   [r"peaux? matures?", r"peaux? agees?", r"anti-?age", r"anti-?rides?"],
    "tous":     [r"tous (?:les )?types? de peaux?", r"tout type de peau",
                 r"toutes? les peaux"],
}

HAIR = {
    "secs":           [r"cheveux (?:tres )?secs"],
    "gras":           [r"cheveux gras", r"cuir chevelu gras"],
    "normaux":        [r"cheveux normaux"],
    "abimes":         [r"cheveux abimes", r"cheveux cassants", r"fourches",
                       r"cheveux devitalises"],
    "colores":        [r"cheveux colores", r"apres coloration"],
    "boucles_frises": [r"cheveux (?:boucles|frises|crepus|ondules)"],
    "pellicules":     [r"pellicules?", r"anti-?pelliculaire"],
    "chute":          [r"chute (?:de|des) cheveux", r"alopecie", r"anti-?chute"],
    "tous":           [r"tous (?:les )?types? de cheveux"],
}

# ---------------------------------------------------------------------------
# CONCERNS — weighted.
#   strong = the product is clearly FOR this. One match is enough.
#   weak   = suggestive but common filler. Needs two.
# ---------------------------------------------------------------------------

CONCERNS = {
    "taches_pigmentaires": {
        "strong": [r"anti-?tache", r"depigmentant", r"hyperpigmentation", r"melasma",
                   r"unifie le teint", r"attenue les taches", r"taches? (?:brunes?|pigmentaires?)"],
        "weak":   [r"eclaircissant", r"\btaches?\b"]},
    "rides_age": {
        "strong": [r"anti-?rides?", r"anti-?age", r"anti-?vieillissement",
                   r"raffermissant", r"\bliftant\b", r"rides? et ridules?"],
        "weak":   [r"\bfermete\b", r"\bcollagene\b", r"\belasticite\b", r"\brides?\b"]},
    "deshydratation": {
        "strong": [r"hydratation intense", r"deshydratee?", r"hydrate en profondeur",
                   r"peaux? (?:tres )?seches?", r"nutrition intense", r"anti-?dessechement"],
        "weak":   [r"hydratant", r"nourrissant", r"\bhydrate\b", r"\bnourrit\b"]},
    "imperfections_acne": {
        "strong": [r"\bacne", r"anti-?imperfections?", r"\bboutons?\b",
                   r"points? noirs?", r"peaux? a tendance acnei?que"],
        "weak":   [r"imperfections?", r"\bpurifiant\b"]},
    "rougeurs_sensibilite": {
        "strong": [r"\brougeurs?\b", r"peaux? sensibles?", r"anti-?irritation",
                   r"\bdemangeaisons?\b", r"\beczema\b", r"peaux? reactives?"],
        "weak":   [r"\bapaisant\b", r"\bcalmant\b", r"\bapaise\b"]},
    "exces_sebum": {
        "strong": [r"exces de sebum", r"seboregulateur", r"regule le sebum",
                   r"\bmatifiant\b", r"peaux? grasses?"],
        "weak":   [r"\bsebum\b", r"\bmatifie\b"]},
    "eclat_teint": {
        "strong": [r"teint terne", r"ravive l eclat", r"\billuminateur\b",
                   r"redonne de l eclat", r"anti-?teint terne"],
        "weak":   [r"\beclat\b", r"\blumineux\b", r"\bradiance\b"]},
    "protection_solaire": {
        "strong": [r"ecran solaire", r"\bspf ?\d+", r"protection solaire",
                   r"\buva\b", r"\buvb\b", r"filtre solaire"],
        "weak":   [r"\bsolaire\b"]},
    "cernes_poches": {
        "strong": [r"\bcernes?\b", r"\bpoches?\b", r"contour des yeux"],
        "weak":   []},
    "pores_dilates": {
        "strong": [r"pores? dilates?", r"resserre les pores"],
        "weak":   [r"\bpores\b"]},
    "chute_cheveux": {
        "strong": [r"chute (?:de|des) cheveux", r"anti-?chute", r"\balopecie\b",
                   r"stimule la pousse", r"pousse des cheveux"],
        "weak":   [r"fortifie les cheveux"]},
    "pellicules": {
        "strong": [r"\bpellicules?\b", r"anti-?pelliculaire"], "weak": []},
    "cheveux_abimes": {
        "strong": [r"cheveux abimes", r"repare les cheveux", r"\bfourches\b",
                   r"cheveux cassants"],
        "weak":   [r"reparateur"]},
    "minceur_detox": {
        "strong": [r"\bminceur\b", r"amincissant", r"brule-?graisse", r"\bcellulite\b",
                   r"perte de poids", r"draineur", r"\bdetox\b"],
        "weak":   [r"\bdrainant\b", r"\bsilhouette\b"]},
    "digestion": {
        "strong": [r"\bdigestion\b", r"\btransit\b", r"flore intestinale",
                   r"\bballonnements?\b", r"\bprobiotique", r"\bconstipation\b",
                   r"confort digestif"],
        "weak":   [r"\bintestin", r"\bestomac\b"]},
    "immunite": {
        "strong": [r"\bimmunite\b", r"systeme immunitaire", r"defenses naturelles",
                   r"voies respiratoires", r"\brhume\b", r"\bgrippe\b"],
        "weak":   [r"\btoux\b", r"\bimmunitaire\b"]},
    "sommeil_stress": {
        "strong": [r"\bsommeil\b", r"\bstress\b", r"\banxiete\b", r"\binsomnie\b",
                   r"\brelaxation\b", r"\bnervosite\b", r"favorise l endormissement"],
        "weak":   [r"\bdetente\b", r"\bzen\b", r"\bcalme\b"]},
    "energie_tonus": {
        "strong": [r"\bfatigue\b", r"coup de fouet", r"\bvitalite\b",
                   r"\bantifatigue\b", r"redonne de l energie"],
        "weak":   [r"\benergie\b", r"\btonus\b", r"\bstimulant\b", r"\bdynamisant\b"]},
    "articulations": {
        "strong": [r"\barticulations?\b", r"\barthrose\b", r"douleurs? articulaires?",
                   r"souplesse articulaire"],
        "weak":   [r"\bcartilage\b"]},
    "memoire_concentration": {
        "strong": [r"\bmemoire\b", r"\bconcentration\b", r"fonctions cognitives"],
        "weak":   [r"\bcerebral\b"]},
    "glycemie_tension": {
        "strong": [r"\bglycemie\b", r"taux de sucre", r"\bcholesterol\b",
                   r"\bdiabete\b", r"tension arterielle"],
        "weak":   [r"\btension\b"]},
    "fertilite": {
        "strong": [r"\bfertilite\b", r"\blibido\b", r"\bvirilite\b",
                   r"\btestosterone\b", r"\bspermatozoides\b"],
        "weak":   [r"\bsexuelle?\b"]},
    "sport_nutrition": {
        "strong": [r"\bmusculation\b", r"masse musculaire", r"\bwhey\b",
                   r"proteines? en poudre", r"recuperation musculaire"],
        "weak":   [r"\bsportifs?\b", r"\bperformance\b"]},
    "cheveux_peau_ongles": {
        "strong": [r"cheveux,? peau et ongles", r"ongles cassants",
                   r"beaute de la peau"],
        "weak":   []},
    "hygiene": {
        "strong": [r"hygiene (?:corporelle|intime|quotidienne)", r"\bdesinfect",
                   r"\bantibacterien\b"],
        "weak":   [r"\bnettoie\b"]},
}

# ---------------------------------------------------------------------------
# FORMAT — first match wins, so specific patterns come first.
# ---------------------------------------------------------------------------

FORMAT = [
    # --- cosmetics -------------------------------------------------------
    ("solaire",             [r"ecran solaire", r"\bspf ?\d+", r"protection solaire"]),
    ("contour_yeux",        [r"contour des yeux", r"soin des yeux", r"anti-?cernes?"]),
    ("demaquillant",        [r"demaquillant", r"eau micellaire", r"lotion micellaire"]),
    ("lotion_tonique",      [r"lotion tonique", r"\btonique\b", r"\bbrume\b"]),
    ("nettoyant",           [r"gel nettoyant", r"nettoyant visage", r"mousse nettoyante",
                             r"gel moussant", r"\bnettoyant\b"]),
    ("gommage",             [r"\bgommage\b", r"\bexfoliant\b", r"\bscrub\b", r"\bpeeling\b"]),
    ("masque",              [r"\bmasque\b"]),
    ("serum",               [r"\bserums?\b"]),
    ("creme_hydratante",    [r"creme hydratante", r"gel hydratant", r"soin de (?:jour|nuit)",
                             r"\bcremes?\b", r"\bfluide\b", r"\bbaume\b"]),
    ("apres_shampooing",    [r"apres-?shampoo?ing", r"conditionneur", r"\bdemelant\b"]),
    ("shampooing",          [r"shampoo?ing"]),
    ("huile_capillaire",    [r"huile capillaire", r"serum capillaire", r"huile pour cheveux"]),
    ("coloration_vegetale", [r"coloration vegetale", r"\bhenne\b", r"\bcoloration\b"]),
    ("deodorant",           [r"\bdeodorant\b", r"anti-?transpirant"]),
    ("dentifrice",          [r"\bdentifrice\b", r"bain de bouche", r"soins? bouche"]),
    ("savon",               [r"\bsavons?\b"]),
    ("lait_corps",          [r"lait corporel", r"lait pour le corps", r"creme corps",
                             r"beurre corporel", r"baume corps"]),
    ("bain",                [r"gel douche", r"bain moussant", r"sels de bain"]),
    ("huile_essentielle",   [r"huile essentielle"]),
    ("hydrolat",            [r"\bhydrolat\b", r"eau florale"]),
    ("argile",              [r"\bargile\b", r"\bghassoul\b", r"\brhassoul\b"]),
    ("parfum",              [r"eau de parfum", r"eau de toilette", r"\bparfum\b"]),
    ("huile_visage",        [r"huile pour le visage", r"huile de soin visage"]),
    # --- food (NEW in v2) -------------------------------------------------
    ("huile_alimentaire",   [r"huile d olive", r"huile alimentaire", r"huile de tournesol",
                             r"huile de colza"]),
    ("epice",               [r"\bepices?\b", r"\bcondiment\b", r"\bpaprika\b", r"\bcumin\b",
                             r"\bcoriandre\b", r"\bcurcuma\b", r"\bcannelle\b", r"\bpoivre\b",
                             r"\bfenouil\b", r"\bbasilic\b", r"\bthym\b", r"\borigan\b",
                             r"\bpersil\b", r"\bmenthe sechee\b", r"\bromarin seche\b",
                             r"\blaurier\b", r"\bgingembre moulu\b", r"\bsel\b", r"\bmoulin\b"]),
    ("tisane",              [r"\btisane\b", r"\binfusion\b", r"\bthe (?:vert|noir|blanc)\b",
                             r"\bthes?\b.*\bbio\b"]),
    ("boisson",             [r"\bjus\b", r"\bboisson\b", r"\bsirop\b", r"\bnectar\b"]),
    ("aliment",             [r"\bpates?\b", r"\bspaghetti\b", r"\bpenne\b", r"\bfarines?\b",
                             r"\bsemoule\b", r"\bcouscous\b", r"\bflocons?\b", r"\bcereales?\b",
                             r"\bmuesli\b", r"\bgranola\b", r"\bbiscuits?\b", r"\bgalettes?\b",
                             r"\blentilles?\b", r"\bpois chiches?\b", r"\bharicots?\b",
                             r"\bquinoa\b", r"\bboulgour\b", r"\briz\b", r"\borge\b",
                             r"\bavoine\b", r"\bsarrasin\b", r"\bble\b", r"\bbsissa\b",
                             r"\bmhames\b", r"\bolives?\b", r"\bconfiture\b", r"\bmiel\b",
                             r"\bbeurre d (?:amande|arachide|noisette|sesame|cacahuete)",
                             r"\bbeurre de sesame\b", r"\bbeurre energetique\b",
                             r"\btahini\b", r"\bhalva\b", r"\bdattes?\b", r"\bfruits secs\b",
                             r"\bamandes?\b", r"\bnoix\b", r"\bnoisettes?\b", r"\bgraines? de\b",
                             r"\bchocolat\b", r"\bcacao\b", r"\bsucre\b", r"\bstevia\b",
                             r"\bcaroube\b", r"\blait\b", r"\blactose\b", r"\bcreme dessert\b",
                             r"\bsemoule\b", r"\bson d avoine\b", r"\bgerme de ble\b",
                             r"\bagave\b", r"\bedulcorant\b", r"\blevure\b", r"\bvinaigre\b",
                             r"\bsans gluten\b", r"\bkonjac\b", r"\bvermicelle\b",
                             r"\bcafe\b", r"\blait vegetal\b", r"\bboite de conserve\b"]),
    # --- supplements ------------------------------------------------------
    ("complement_gelules",  [r"\bgelules?\b", r"\bcomprimes?\b", r"\bcapsules?\b",
                             r"\bampoules?\b"]),
    ("complement_poudre",   [r"poudre de", r"\bpoudre\b", r"\bspiruline\b", r"\bmoringa\b"]),
    ("huile_vegetale",      [r"huile vegetale", r"huile de \w+", r"\bmacerat\b"]),
    # --- non-consumable ---------------------------------------------------
    ("menage",              [r"\blessive\b", r"nettoyant menager", r"menage ecologique",
                             r"liquide vaisselle", r"\bdetergent\b"]),
    ("accessoire",          [r"\bbrosse\b", r"\bgant\b", r"\bbonnet\b", r"\bsac\b",
                             r"\bpeigne\b", r"\bpaille\b", r"\bcoton\b", r"\bpinceau\b",
                             r"\bcorbeille\b", r"\bbouteille\b", r"\bflacon\b",
                             r"\bpot vide\b", r"\bmoulin\b", r"\bboite\b", r"\bcoupelle\b"]),
]

# Category fallback: if no pattern matched, infer the family from the WooCommerce
# category tree. Catches food and supplements whose names are unusual.
CATEGORY_FALLBACK = [
    (r"complements? alimentaires?|vitamines?|mineraux", "complement_gelules"),
    (r"epicerie|alimentation|superaliments?|petit dejeuner|sans gluten|keto",
     "aliment"),
    (r"boissons?|thes? et infusions?",                  "tisane"),
    (r"maison|menage|ecolo|zero dechet",                "menage"),
    (r"soin et beaute|visage|corps|cheveux",            "creme_hydratante"),
]

# ---------------------------------------------------------------------------
# ZONE — where on the body the product goes. Format alone is not enough:
# a lip scrub and a face scrub are both "gommage".
# ---------------------------------------------------------------------------

ZONE = [
    ("levres",  [r"\blevres?\b", r"baume a levres", r"stick a levres", r"\blip\b",
                 r"\bgloss\b", r"\brouge a levres\b"]),
    ("yeux",    [r"contour des yeux", r"\bcils\b", r"\bsourcils?\b", r"\bcernes?\b",
                 r"soin des yeux", r"\bregard\b"]),
    ("mains",   [r"\bmains?\b", r"\bongles?\b", r"\bmanucure\b"]),
    ("pieds",   [r"\bpieds?\b", r"\btalons?\b"]),
    ("bouche",  [r"\bdents?\b", r"\bdentifrice\b", r"bain de bouche", r"\bgencives?\b"]),
    ("cheveux", [r"\bcheveux\b", r"\bcapillaire\b", r"cuir chevelu", r"shampoo?ing",
                 r"\bbarbe\b"]),
    ("visage",  [r"\bvisage\b", r"\bteint\b", r"\bpeau du visage\b", r"\bjoues?\b",
                 r"\bfront\b", r"\bnez\b", r"\bpores\b"]),
    ("corps",   [r"\bcorps\b", r"\bjambes?\b", r"\bbras\b", r"\bventre\b",
                 r"\bvergetures?\b", r"\baisselles?\b", r"\bdouche\b"]),
]

# When no zone word appears, infer it from the format.
ZONE_BY_FORMAT = {
    "nettoyant": "visage", "demaquillant": "visage", "lotion_tonique": "visage",
    "serum": "visage", "creme_hydratante": "visage", "contour_yeux": "yeux",
    "solaire": "visage", "huile_visage": "visage", "hydrolat": "visage",
    "shampooing": "cheveux", "apres_shampooing": "cheveux",
    "huile_capillaire": "cheveux", "coloration_vegetale": "cheveux",
    "lait_corps": "corps", "deodorant": "corps", "bain": "corps",
    "dentifrice": "bouche",
    "complement_gelules": "oral", "complement_poudre": "oral", "tisane": "oral",
    "aliment": "oral", "epice": "oral", "huile_alimentaire": "oral", "boisson": "oral",
    "menage": "maison", "accessoire": "aucune",
}

STEP_BY_FORMAT = {
    "nettoyant": "nettoyage", "demaquillant": "nettoyage", "savon": "nettoyage",
    "gommage": "nettoyage", "shampooing": "nettoyage", "bain": "nettoyage",
    "lotion_tonique": "tonification", "hydrolat": "tonification",
    "serum": "traitement", "masque": "traitement", "argile": "traitement",
    "huile_essentielle": "traitement",
    "creme_hydratante": "hydratation", "lait_corps": "hydratation",
    "huile_visage": "hydratation", "huile_vegetale": "hydratation",
    "apres_shampooing": "hydratation", "huile_capillaire": "hydratation",
    "solaire": "protection",
    "contour_yeux": "soin_cible", "deodorant": "soin_cible",
    "dentifrice": "soin_cible", "coloration_vegetale": "soin_cible",
    "parfum": "soin_cible",
    "complement_gelules": "complement_oral", "complement_poudre": "complement_oral",
    "tisane": "complement_oral",
}

NON_APPLICABLE = {"aliment", "epice", "huile_alimentaire", "boisson",
                  "menage", "accessoire", "autre"}

INGREDIENTS = [
    "aloe vera", "huile d argan", "huile de jojoba", "huile d avocat", "huile d olive",
    "huile de coco", "huile de ricin", "huile de nigelle", "huile d amande douce",
    "huile de figue de barbarie", "beurre de karite", "bave d escargot",
    "acide hyaluronique", "vitamine c", "vitamine e", "vitamine a", "vitamine d",
    "niacinamide", "retinol", "collagene", "tea tree", "lavande", "romarin",
    "camomille", "the vert", "curcuma", "gingembre", "spiruline", "moringa",
    "ginseng", "argile verte", "ghassoul", "charbon", "miel", "propolis",
    "gelee royale", "zinc", "magnesium", "fer", "omega 3", "probiotiques",
    "glycerine", "acide salicylique", "beurre de cacao", "cire d abeille",
]

PACK_RE = re.compile(r"(^|\s)(pack|duo|trio|coffret|routine|kit|set|lot)(\s|$)")
SIZE_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s?"
    r"(ml|cl|l|g|gr|grammes?|kg|gelules?|comprimes?|capsules?|sachets?)\b")


def find(text: str, patterns: dict) -> list:
    return [k for k, pats in patterns.items()
            if any(re.search(p, text) for p in pats)]


def find_concerns(text: str, title: str = "") -> list:
    """Weighted: strong match = 2 pts, each weak = 1 pt, keep >= 2 pts.

    A match in the TITLE counts for far more than one in the description.
    A product called "Tisane Minceur" is a slimming product, even if its text
    dwells on transit and drainage — otherwise it leads the results for
    someone who asked about digestion, which is the wrong answer to give.
    """
    scored = []
    for name, pats in CONCERNS.items():
        score = 0
        if any(re.search(p, text) for p in pats["strong"]):
            score += 2
        score += sum(1 for p in pats["weak"] if re.search(p, text))
        if title and any(re.search(p, title) for p in pats["strong"] + pats["weak"]):
            score += 3
        if score >= 2:
            scored.append((score, name))
    scored.sort(reverse=True)
    return [n for _, n in scored[:4]]


def extract(p: dict) -> dict:
    title = norm(p.get("name", ""))
    body = norm((p.get("short_desc") or "") + " " + (p.get("description") or ""))
    cats = norm(p.get("categories") or p.get("categories_all") or "")
    full = f"{title} {body} {cats}"
    has_text = len(body) > 60

    # --- format -----------------------------------------------------------
    is_pack = bool(PACK_RE.search(title))
    fmt = None
    if is_pack:
        fmt = "pack"
    else:
        for name, pats in FORMAT:                      # title first
            if any(re.search(pt, title) for pt in pats):
                fmt = name
                break
        if fmt is None:
            for name, pats in FORMAT:                  # then body
                if any(re.search(pt, body) for pt in pats):
                    fmt = name
                    break
        if fmt is None:                                # then category
            for pat, name in CATEGORY_FALLBACK:
                if re.search(pat, cats):
                    fmt = name
                    break
        if fmt is None:
            fmt = "autre"

    # --- zone -------------------------------------------------------------
    zone = None
    for name, pats in ZONE:                       # title wins
        if any(re.search(pt, title) for pt in pats):
            zone = name
            break
    if zone is None:
        zone = ZONE_BY_FORMAT.get(fmt)
    if zone is None:
        for name, pats in ZONE:                   # then body
            if any(re.search(pt, body) for pt in pats):
                zone = name
                break
    if zone is None:
        zone = "polyvalent"

    topical = fmt not in NON_APPLICABLE and fmt not in (
        "complement_gelules", "complement_poudre", "tisane")

    # --- skin / hair ------------------------------------------------------
    skin = find(full, SKIN)
    if re.search(r"mixtes? a grasses?", full):
        skin = sorted(set(skin) | {"mixte", "grasse"})
    if "tous" in skin and len(skin) > 1:
        skin.remove("tous")

    hair = find(full, HAIR)
    if "tous" in hair and len(hair) > 1:
        hair.remove("tous")

    if fmt in NON_APPLICABLE:
        skin, hair = [], []

    # --- concerns ---------------------------------------------------------
    concerns = find_concerns(full, title)
    if fmt in ("accessoire", "menage", "epice", "aliment", "huile_alimentaire"):
        concerns = [c for c in concerns
                    if c in ("digestion", "minceur_detox", "sport_nutrition",
                             "glycemie_tension", "energie_tonus")]
    if not concerns:
        concerns = ["aucun"]

    # --- usage time -------------------------------------------------------
    usage = []
    if re.search(r"\ble matin\b|matin et soir|soin de jour|\bau reveil\b", full):
        usage.append("matin")
    if re.search(r"\ble soir\b|matin et soir|soin de nuit|avant le coucher|\bla nuit\b", full):
        usage.append("soir")
    if fmt == "solaire":
        usage = ["matin"]
    if not usage:
        usage = ["indifferent"]

    # --- step -------------------------------------------------------------
    step = STEP_BY_FORMAT.get(fmt, "non_applicable")
    if fmt == "pack":
        step = "soin_cible"

    # --- size, ingredients, summary --------------------------------------
    m = SIZE_RE.search(title) or SIZE_RE.search(body)
    size = f"{m.group(1)} {m.group(2)}" if m else None
    ings = [i for i in INGREDIENTS if i in full][:6]

    raw_short = re.sub(r"<[^>]+>", " ", p.get("short_desc") or "")
    raw_short = html.unescape(re.sub(r"\s+", " ", raw_short)).strip()
    summary = (raw_short.split(".")[0][:120] + ".") if raw_short else (p.get("name") or "")

    # --- confidence: did we UNDERSTAND the product? -----------------------
    if fmt == "autre":
        conf = 0.30                       # genuinely unclassified
    elif not has_text and not is_pack:
        conf = 0.45                       # classified on title alone
    elif fmt in NON_APPLICABLE:
        conf = 0.85                       # food/accessory: correctly out of scope
    elif not topical:
        conf = 0.80 if concerns != ["aucun"] else 0.60   # supplement
    else:
        conf = 0.55
        if skin or hair:
            conf += 0.25
        if concerns != ["aucun"]:
            conf += 0.15
        if size:
            conf += 0.05
    conf = round(min(conf, 0.95), 2)

    return {
        "id": p["id"],
        "product_format": fmt,
        "zone": zone,
        "skin_type": skin,
        "hair_type": hair,
        "concerns": concerns,
        "usage_time": usage,
        "routine_step": step,
        "key_ingredients": ings,
        "volume_size": size,
        "is_pack": is_pack,
        "pack_contents_raw": [],
        "benefit_summary": summary,
        "confidence": conf,
        "extraction_method": "rules_v2",
        "name": p.get("name"), "brand": p.get("brand"),
        "categories": p.get("categories"), "price": p.get("price"),
        "regular_price": p.get("regular_price"), "stock": p.get("stock"),
        "stock_status": p.get("stock_status"), "total_sales": p.get("total_sales"),
        "rating": p.get("rating"), "image_id": p.get("image_id"), "slug": p.get("slug"),
    }


# NOTE: the CLI portion of enrich_rules.py is intentionally omitted here.
# This module exists only to expose extract() to the service.
