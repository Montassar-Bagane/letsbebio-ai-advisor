"""Agent conversationnel.

The difference from /recommend: this runs a LOOP. The model decides what to do
next based on what the previous step returned, which is what makes it an agent
rather than a pipeline. A shopper says "j'ai des boutons", the agent asks a
follow-up, searches, sees the prices, and searches again when told it's too
expensive. None of that path can be scripted in advance.

The safety rule from /interpret still holds, and matters more here:

    The agent may ask, decide what to look up, and phrase the answer.
    It may NOT invent products.

Every product shown to the shopper comes from a tool result, never from the
model's own text. The card list returned to the interface is built from what
the tools returned, so a hallucinated product name in the prose has nothing
to render and is caught by the check at the end of the loop.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from types import SimpleNamespace

from . import catalogue, derja, scoring, semantic
from .settings import settings

log = logging.getLogger("agent")

MAX_STEPS = 8          # tool iterations per turn; a guard against loops
MAX_HISTORY = 8        # conversation turns kept (token budget)


# ---------------------------------------------------------------------------
# Tools — thin wrappers over the deterministic engine
# ---------------------------------------------------------------------------

def _req(domain, concerns, skin_type=None, usage_time=None,
         budget_max=None, brand=None, in_stock_only=True):
    return SimpleNamespace(
        domain=domain, concerns=concerns, skin_type=skin_type,
        usage_time=usage_time, budget_max=budget_max, brand=brand,
        in_stock_only=in_stock_only)


def _compact(p: dict, live: dict) -> dict:
    """What the MODEL sees: enough to reason about, nothing more."""
    lv = live.get(p["id"], {})
    return {
        "id": p["id"],
        "nom": p.get("name"),
        "marque": p.get("brand"),
        "prix": lv.get("price", p.get("price")),
        "type_peau": p.get("skin_type") or [],
        "preoccupations": p.get("concerns") or [],
        "etape": p.get("routine_step"),
        "format": p.get("product_format"),
        "en_stock": (lv.get("stock_status", p.get("stock_status")) or "instock")
                    == "instock",
    }


def tool_lister_options(domaine: str = "visage") -> dict:
    """What the catalogue can actually answer for, with counts."""
    if domaine not in scoring.DOMAINS:
        return {"erreur": f"domaine inconnu: {domaine}",
                "domaines_valides": list(scoring.DOMAINS)}
    st = catalogue.get()
    d = scoring.DOMAINS[domaine]
    allow = set(d["concerns"])
    type_key = "hair_type" if d["type"] == "hair" else "skin_type"

    concerns, types = {}, {}
    for p in st["products"]:
        if p.get("is_pack") or not scoring.in_domain(p, domaine):
            continue
        for c in p.get("concerns") or []:
            if c in allow:
                concerns[c] = concerns.get(c, 0) + 1
        if d["type"]:
            for t in p.get(type_key) or []:
                if t != "tous":
                    types[t] = types.get(t, 0) + 1

    return {
        "domaine": domaine,
        "preoccupations": [{"valeur": k, "produits": v} for k, v in
                           sorted(concerns.items(), key=lambda x: -x[1]) if v >= 3],
        "types": [{"valeur": k, "produits": v} for k, v in
                  sorted(types.items(), key=lambda x: -x[1])],
    }


def tool_chercher_produits(domaine, preoccupations, type_peau=None,
                           budget_max=None, marque=None, limite=6) -> dict:
    st = catalogue.get()
    valid = set(scoring.DOMAINS.get(domaine, {}).get("concerns", []))
    concerns = [c for c in (preoccupations or []) if c in valid]
    if not concerns:
        return {"erreur": "aucune préoccupation valide pour ce domaine",
                "preoccupations_valides": sorted(valid)}

    req = _req(domaine, concerns, type_peau, None, budget_max, marque)
    scored = scoring.candidates(st["products"], req)
    relaxed = False
    if not scored and type_peau:
        req_relaxed = _req(domaine, concerns, None, None, budget_max, marque)
        scored = scoring.candidates(st["products"], req_relaxed)
        relaxed = bool(scored)

    top = scored[: max(1, min(int(limite or 5), 8))]
    live = catalogue.fetch_live([p["id"] for _, p in top])

    res = {
        "total_correspondants": len(scored),
        "produits": [_compact(p, live) for _, p in top],
    }
    if relaxed:
        res["remarque"] = (f"Aucun produit spécifique pour '{type_peau}', "
                           f"mais ces soins traitent efficacement '{', '.join(concerns)}' "
                           f"et conviennent à tous types.")
    return res


def tool_construire_routine(domaine, preoccupations, type_peau=None,
                            moment=None, budget_max=None) -> dict:
    st = catalogue.get()
    valid = set(scoring.DOMAINS.get(domaine, {}).get("concerns", []))
    concerns = [c for c in (preoccupations or []) if c in valid]
    if not concerns:
        return {"erreur": "aucune préoccupation valide pour ce domaine",
                "preoccupations_valides": sorted(valid)}

    req = _req(domaine, concerns, type_peau, moment, budget_max)
    scored = scoring.candidates(st["products"], req)
    relaxed = False
    if not scored and type_peau:
        req_relaxed = _req(domaine, concerns, None, moment, budget_max)
        scored = scoring.candidates(st["products"], req_relaxed)
        relaxed = bool(scored)

    steps = scoring.build_routine(scored, domaine)
    packs = scoring.matching_packs(st["packs"], req)

    ids = [p["id"] for _, _, p in steps] + [r["id"] for r in packs]
    live = catalogue.fetch_live(ids)

    total = 0.0
    etapes = []
    for step, sc, p in steps:
        c = _compact(p, live)
        c["etape_routine"] = step
        c["raison"] = sc["reason"]
        etapes.append(c)
        try:
            total += float(c["prix"] or 0)
        except (TypeError, ValueError):
            pass

    res = {
        "etapes": etapes,
        "total": round(total, 3),
        "total_correspondants": len(scored),
        "packs": [{"id": r["id"], "nom": r.get("name"),
                   "prix": live.get(r["id"], {}).get("price", r.get("price"))}
                  for r in packs[:2]],
    }
    if relaxed:
        res["remarque"] = (f"Aucun produit spécifique pour '{type_peau}', "
                           f"mais ces soins traitent efficacement '{', '.join(concerns)}' "
                           f"et conviennent à tous types.")
    return res


def tool_recherche_semantique(texte: str, domaine: str | None = None,
                              type_peau: str | None = None,
                              limite: int = 5) -> dict:
    """Retrieval by meaning rather than by vocabulary.

    This is the recovery path when keyword search returns nothing: a customer
    saying "cuir chevelu gras avec des squames" describes dandruff without
    using the word, and no pattern in the extraction matches it.

    Crucially, semantic retrieval does NOT bypass the safety rules. The
    candidate set is restricted to products the deterministic engine already
    considers admissible for the domain and skin type, so a product declaring
    an incompatible skin type can never be surfaced by similarity alone.
    """
    if not semantic.available():
        return {"erreur": "recherche semantique indisponible",
                "conseil": "utilise chercher_produits"}

    st = catalogue.get()
    allowed = None
    if domaine in scoring.DOMAINS:
        allowed = set()
        for p in st["products"]:
            if p.get("is_pack") or not scoring.in_domain(p, domaine):
                continue
            if type_peau and scoring.DOMAINS[domaine]["type"]:
                key = ("hair_type" if scoring.DOMAINS[domaine]["type"] == "hair"
                       else "skin_type")
                declared = p.get(key) or []
                # a stated mismatch disqualifies, an empty field does not
                if declared and type_peau not in declared and "tous" not in declared:
                    continue
            allowed.add(p["id"])

    hits = semantic.search(texte, top_k=max(1, min(int(limite or 5), 10)),
                           allowed_ids=allowed)
    if not hits:
        return {"produits": [], "total_correspondants": 0,
                "note": "aucun produit proche de cette description"}

    live = catalogue.fetch_live([pid for pid, _ in hits])
    produits = []
    for pid, score in hits:
        p = st["by_id"].get(pid)
        if not p:
            continue
        c = _compact(p, live)
        c["proximite"] = score
        produits.append(c)

    return {"produits": produits, "total_correspondants": len(produits),
            "methode": "semantique"}


TOOLS = {
    "lister_options": tool_lister_options,
    "recherche_semantique": tool_recherche_semantique,
    "chercher_produits": tool_chercher_produits,
    "construire_routine": tool_construire_routine,
}

TOOL_SCHEMA = [
    {"type": "function", "function": {
        "name": "lister_options",
        "description": "Valeurs disponibles au catalogue et nombre de produits.",
        "parameters": {"type": "object", "properties": {
            "domaine": {"type": "string",
                        "enum": ["visage", "cheveux", "corps", "interieur"]}},
            "required": ["domaine"]}}},

    {"type": "function", "function": {
        "name": "chercher_produits",
        "description": "Cherche des produits pour un profil.",
        "parameters": {"type": "object", "properties": {
            "domaine": {"type": "string",
                        "enum": ["visage", "cheveux", "corps", "interieur"]},
            "preoccupations": {"type": "array", "items": {"type": "string"}},
            "type_peau": {"type": ["string", "null"]},
            "budget_max": {"type": ["number", "null"]},
            "marque": {"type": ["string", "null"]},
            "limite": {"type": ["integer", "null"]}},
            "required": ["domaine", "preoccupations"]}}},

    {"type": "function", "function": {
        "name": "recherche_semantique",
        "description": "Recherche par le SENS d'une description libre, pas par "
                       "mots-cles. A utiliser quand chercher_produits ou "
                       "construire_routine ne renvoie rien, ou quand le client "
                       "decrit un probleme sans vocabulaire standard.",
        "parameters": {"type": "object", "properties": {
            "texte": {"type": "string",
                      "description": "la description du client, telle quelle"},
            "domaine": {"type": ["string", "null"],
                        "description": "visage, cheveux, corps ou interieur"},
            "type_peau": {"type": ["string", "null"]},
            "limite": {"type": ["integer", "null"]}},
            "required": ["texte"]}}},

    {"type": "function", "function": {
        "name": "construire_routine",
        "description": "Routine ordonnée complète avec prix total.",
        "parameters": {"type": "object", "properties": {
            "domaine": {"type": "string",
                        "enum": ["visage", "cheveux", "corps", "interieur"]},
            "preoccupations": {"type": "array", "items": {"type": "string"}},
            "type_peau": {"type": ["string", "null"]},
            "moment": {"type": ["string", "null"],
                       "description": "matin ou soir"},
            "budget_max": {"type": ["number", "null"]}},
            "required": ["domaine", "preoccupations"]}}},
]


def _parse_followup(text: str) -> tuple[str, list]:
    """Extract structured follow-up questions from the agent reply.

    The model is instructed to append a JSON block delimited by
    <<<QUESTIONS>>> ... <<<END>>> at the end of its reply when it needs
    clarification.  This function strips that block and returns the clean
    reply text plus the parsed questions list.
    """
    import re as _re
    marker_start = "<<<QUESTIONS>>>"
    marker_end = "<<<END>>>"

    idx = text.find(marker_start)
    if idx == -1:
        return text.strip(), []

    clean = text[:idx].strip()
    block = text[idx + len(marker_start):]
    end_idx = block.find(marker_end)
    if end_idx != -1:
        block = block[:end_idx]

    # The model sometimes wraps JSON in markdown code fences or uses smart quotes
    block = block.strip()
    block = _re.sub(r"^```(?:json)?\s*", "", block)
    block = _re.sub(r"\s*```$", "", block)
    block = block.replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"')
    # Strip trailing commas before closing brackets/braces (common LLM JSON quirk)
    block = _re.sub(r",\s*([\]}])", r"\1", block)

    try:
        questions = json.loads(block)
        if not isinstance(questions, list):
            questions = [questions]
        # Validate structure
        validated = []
        for q in questions:
            if isinstance(q, dict) and "question" in q and "options" in q:
                opts = q["options"]
                if isinstance(opts, list) and len(opts) >= 2:
                    validated.append({
                        "question": str(q["question"]),
                        "options": [str(o) for o in opts[:6]],  # cap at 6
                    })
        return clean, validated
    except (json.JSONDecodeError, TypeError, KeyError):
        return clean, []


def _system(script: str = "latin") -> str:
    """Kept deliberately short: every token here is re-sent on each loop
    iteration, and free API tiers are limited by tokens per minute."""
    return """Conseiller beauté d'une boutique tunisienne de produits naturels.
Français, ton simple et chaleureux, 2-3 phrases max.

RÈGLE ABSOLUE : ne cite JAMAIS un produit hors résultat d'outil. Rien ne correspond ->
dis-le franchement.

Traduis le langage courant en vocabulaire outil :
boutons/acné -> imperfections_acne | brille/gras -> exces_sebum
taches -> taches_pigmentaires | rides -> rides_age | tiraille/sec -> deshydratation
rougeurs -> rougeurs_sensibilite | teint terne -> eclat_teint | soleil -> protection_solaire
cernes -> cernes_poches | chute cheveux -> chute_cheveux | pellicules -> pellicules
fatigue -> energie_tonus | digestion -> digestion | sommeil -> sommeil_stress
immunité -> immunite | minceur -> minceur_detox
Peau : normale seche mixte grasse sensible acneique mature
Cheveux : secs gras normaux abimes colores boucles_frises pellicules chute
Domaines : visage cheveux corps interieur (compléments)

DÉMARCHE CONSEIL (TRÈS IMPORTANT) :
1. QUALIFICATION D'ABORD : Si la demande du client est générale, vague ou s'il manque des précisions clés (type de peau/cheveux, moment, budget), N'APPELLE AUCUN OUTIL tout de suite. Réponds chaleureusement en 1-2 phrases et pose 2 questions avec options (bloc <<<QUESTIONS>>>) pour qualifier son besoin.
2. RECOMMANDATION : Appelle construire_routine ou chercher_produits UNIQUEMENT quand le besoin ET le type de peau/cheveux sont précisés (ou après que le client a répondu aux options).
3. AFFINAGE SANS RÉPÉTITION :
- Ne redemande JAMAIS une information déjà fournie (type de peau, cheveux, budget). Si le client a déjà répondu au budget ou sélectionné "Peu importe", INTERDICTION STRICTE de reposer une question de budget !
- Après avoir présenté les produits, pose UNE SEULE question courte d'affinage (1 question max, pas de budget !), par exemple :
  [{"question": "Ces produits vous conviennent-ils ?", "options": ["Ajouter un soin ciblé", "Voir d'autres options", "C'est parfait !"]}]

Un seul outil par besoin, puis RÉPONDS. N'appelle jamais deux fois le même outil avec les mêmes arguments.
Par DÉFAUT utilise construire_routine pour une routine complète, et chercher_produits uniquement s'il demande explicitement un seul produit (« juste une crème », « un sérum »).
Trop cher -> relance avec budget_max.
Valeur incertaine -> lister_options.
AUCUN resultat -> recherche_semantique avec la phrase du client telle quelle,
puis réponds avec ce qu'elle renvoie. Ne dis jamais "rien trouvé" sans l'avoir essayée.

Cite les prix en DINARS (DT), jamais en euros. Le total vient du champ "total" de l'outil : ne le calcule jamais toi-même.
Chaque message porte sur UN besoin. Réponds à celui-là seulement.

PRÉSENTATION DES PRODUITS (TRÈS IMPORTANT) :
Les fiches produits s'affichent déjà automatiquement sous ton message dans l'interface (avec nom, marque, contenance, prix en DT et bouton panier).
Par conséquent, dans ton texte :
- Rédige UNIQUEMENT 1 à 2 phrases de conseil simples et chaleureuses pour introduire la sélection et expliquer pourquoi ces soins conviennent à son profil (ex: « Voici une sélection de soins fortifiants et antichute adaptés à votre profil : »).
- Si l'outil contient une 'remarque' (filtre assoupli), explique gentiment que ces soins ciblent parfaitement son besoin et conviennent à tous types de peau/cheveux (y compris le sien).
- NE FAIS JAMAIS de liste à puces ni d'énumération des produits ou de leurs prix dans ton texte (c'est redondant avec les cartes).
- Pas d'emoji, pas de listes longues.
Problème médical (douleur, lésion, grossesse + traitement) -> oriente vers un pharmacien avant l'achat.

BLOC QUESTIONS INTERACTIVES (FORMULAIRE À CHOIX MULTIPLES) :
Quand tu as besoin de précisions ou pour affiner, ajoute ce bloc à la fin de ta réponse dans ce format EXACT :

<<<QUESTIONS>>>
[
  {"question": "Quel est votre type de peau ?", "options": ["Grasse", "Mixte", "Sèche", "Normale", "Sensible"]},
  {"question": "Quel est votre budget ?", "options": ["Moins de 50 DT", "50 à 100 DT", "Plus de 100 DT", "Peu importe"]}
]
<<<END>>>

Règles pour les options :
- Pendant la qualification initiale : regroupe 2 questions clés complémentaires (ex: type + budget).
- Après présentation des produits : UNE SEULE question courte pour savoir si cela lui convient (JAMAIS de question budget répétée).
- 2 à 4 options claires et courtes (1-3 mots max) par question.
- En français simple.
- Exemples selon la situation :
  * Premier contact / besoin vague :
    [{"question": "Quel domaine vous intéresse ?", "options": ["Soins Visage", "Cheveux", "Corps & Bain", "Bien-être"]},
     {"question": "Votre priorité ?", "options": ["Routine complète", "Problème ciblé", "Découverte"]}]
  * Visage sans type de peau :
    [{"question": "Quel est votre type de peau ?", "options": ["Grasse", "Mixte", "Sèche", "Normale", "Sensible"]},
     {"question": "Quel est votre budget ?", "options": ["Moins de 50 DT", "50 à 100 DT", "Plus de 100 DT", "Peu importe"]}]
  * Cheveux sans type :
    [{"question": "Quel est votre type de cheveux ?", "options": ["Secs / Abîmés", "Gras", "Chute / Fins", "Pellicules", "Bouclés"]},
     {"question": "Votre budget ?", "options": ["Moins de 50 DT", "50 à 100 DT", "Plus de 100 DT", "Peu importe"]}]
  * Après routine / produits présentés (1 seule question, JAMAIS de budget) :
    [{"question": "Ces produits vous conviennent-ils ?", "options": ["Compléter la routine", "Voir d'autres options", "C'est parfait !"]}]
""" + derja.prompt_guidance(script)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def _call_llm(messages: list, _retry: int = 2) -> dict:
    payload = json.dumps({
        "model": settings.LLM_MODEL,
        "messages": messages,
        "tools": TOOL_SCHEMA,
        "tool_choice": "auto",
        "temperature": 0.3,
        "max_tokens": 700,
    }).encode()

    req = urllib.request.Request(
        settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "reco-engine/1.0",
            **({"authorization": "Bearer " + settings.LLM_API_KEY}
               if settings.LLM_API_KEY else {}),
        },
        method="POST")

    try:
        with urllib.request.urlopen(req, timeout=settings.LLM_TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # Free tiers meter tokens per minute. The provider tells us how long
        # to wait, so honour that rather than guessing — and retry twice,
        # since a single turn can span two windows.
        if e.code == 429 and _retry > 0:
            import re as _re
            import time
            wait = 12.0
            try:
                body = e.read().decode()
                m = _re.search(r"try again in ([\d.]+)s", body)
                if m:
                    wait = min(float(m.group(1)) + 1.5, 25.0)
            except Exception:
                pass
            log.info("rate limited, waiting %.1fs", wait)
            time.sleep(wait)
            return _call_llm(messages, _retry - 1)
        raise


def run(history: list, message: str) -> dict:
    """One conversational turn. Returns the reply plus the products the tools
    actually surfaced, so the interface renders real cards, never model prose."""
    # The reply language follows the script the customer used, so the system
    # prompt is built per turn rather than once.
    script = derja.detect_script(message)
    messages = [{"role": "system", "content": _system(script)}]
    for m in history[-MAX_HISTORY:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": str(m["content"])[:600]})
    # A deterministic reading of the sentence is attached when the customer
    # writes in Derja or Arabizi. The model is far more reliable at choosing a
    # tool than at decoding "3andi 7boub", so the rules do the decoding and the
    # model does the deciding.
    d = derja.analyse(message)
    if d["is_derja"] and (d["concerns"] or d["domain"]):
        note = ["[lecture automatique de la demande en derja]"]
        if d["domain"]:
            note.append(f"domaine probable: {d['domain']}")
        if d["skin_type"]:
            note.append(f"type de peau probable: {d['skin_type']}")
        if d["concerns"]:
            note.append(f"preoccupations probables: {', '.join(d['concerns'])}")
        note.append("Verifie que cela correspond, puis utilise les outils.")
        messages.append({"role": "user", "content": message})
        messages.append({"role": "system", "content": " | ".join(note)})
    else:
        messages.append({"role": "user", "content": message})

    # Only the LAST relevant tool result is shown. Accumulating every product
    # any tool touched piles up cards across turns and stops matching what the
    # agent actually said.
    routine: list = []
    latest_search: list = []
    trace: list = []
    seen_calls: set = set()

    for step in range(MAX_STEPS):
        try:
            data = _call_llm(messages)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass
            log.warning("agent LLM error %s: %s", e.code, body)
            # Model names are withdrawn by providers without notice, and the
            # resulting 404 is indistinguishable from a broken key unless the
            # cause is named.
            if e.code == 404 and "model" in body.lower():
                log.warning("  -> the configured model no longer exists. "
                            "Run 'make models' to list what is available, "
                            "then 'make set-model MODEL=<id>'.")
                raise RuntimeError("llm_model_not_found")
            if e.code in (401, 403):
                raise RuntimeError("llm_bad_key")
            # Tool calling is what makes this an agent rather than a chatbot.
            # Many models on the same endpoint do not support it, and the
            # resulting 400 says nothing useful unless it is named.
            if e.code == 400 and "tool" in body.lower():
                log.warning("  -> this model cannot call tools, which the agent "
                            "requires. Run 'make models' and choose one marked "
                            "[tools].")
                raise RuntimeError("llm_no_tools")
            raise RuntimeError("llm_unavailable")
        except Exception as e:
            log.warning("agent LLM error: %s: %s", type(e).__name__, e)
            raise RuntimeError("llm_unavailable")

        choice = data["choices"][0]["message"]
        calls = choice.get("tool_calls") or []

        if not calls:
            raw_reply = derja.clean_reply((choice.get("content") or "").strip())
            reply, followup = _parse_followup(raw_reply)
            return {
                "reply": reply or "Pouvez-vous préciser votre besoin ?",
                "produits": routine or latest_search[:4],
                "routine": routine,
                "etapes_outils": trace,
                "followup_questions": followup,
                "history": [m for m in messages[1:] if m.get("role") in
                            ("user", "assistant") and m.get("content")]
                           + [{"role": "assistant", "content": reply}],
            }

        messages.append({
            "role": "assistant",
            "content": choice.get("content") or "",
            "tool_calls": calls,
        })

        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            # Strip null values: some models send explicit null for optional
            # params, which the provider rejects as a schema violation.
            args = {k: v for k, v in args.items() if v is not None}

            # A model that repeats the same call is stuck. Say so plainly
            # instead of letting it burn the whole loop budget.
            sig = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
            fn = TOOLS.get(name)
            if sig in seen_calls:
                result = {"note": "Tu as déjà fait cet appel avec les mêmes "
                                  "arguments. Utilise le résultat précédent et "
                                  "réponds maintenant au client."}
            elif not fn:
                result = {"erreur": f"outil inconnu: {name}"}
            else:
                seen_calls.add(sig)
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = {"erreur": f"arguments invalides: {e}"}
                except Exception as e:                       # never kill the turn
                    log.exception("tool %s failed", name)
                    result = {"erreur": str(e)}

            # a routine supersedes a loose search; a new search replaces the old
            if result.get("etapes"):
                routine = result["etapes"]
                latest_search = []
            elif result.get("produits"):
                latest_search = result["produits"]

            trace.append({"outil": name, "arguments": args,
                          "resultats": len(result.get("produits")
                                           or result.get("etapes") or [])})

            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": json.dumps(result, ensure_ascii=False)[:1800],
            })

    # Loop guard hit. Rather than apologise while holding perfectly good
    # results, ask the model once more with tools switched off so it has no
    # choice but to answer in words.
    log.warning("agent hit MAX_STEPS, forcing a written answer")
    try:
        messages.append({"role": "user", "content":
                         "Réponds maintenant au client en français, en te basant "
                         "sur les résultats ci-dessus. N'appelle plus d'outil."})
        payload = json.dumps({
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 400,
        }).encode()
        req = urllib.request.Request(
            settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
            data=payload,
            headers={"content-type": "application/json",
                     "accept": "application/json",
                     "user-agent": "reco-engine/1.0",
                     **({"authorization": "Bearer " + settings.LLM_API_KEY}
                        if settings.LLM_API_KEY else {})},
            method="POST")
        with urllib.request.urlopen(req, timeout=settings.LLM_TIMEOUT) as resp:
            forced = json.load(resp)
        raw_reply = derja.clean_reply(
            (forced["choices"][0]["message"].get("content") or "").strip())
    except Exception as e:
        log.warning("forced answer failed: %s", e)
        raw_reply = ""

    reply, followup = _parse_followup(raw_reply)
    return {
        "reply": reply or "Voici ce que j'ai trouvé pour vous.",
        "produits": routine or latest_search[:4],
        "routine": routine,
        "etapes_outils": trace,
        "followup_questions": followup,
        "history": history + [{"role": "user", "content": message}],
    }
