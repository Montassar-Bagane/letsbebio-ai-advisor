"""Tunisian Arabic (Derja) and Arabizi understanding.

Why this is a separate module
-----------------------------
Tunisian customers rarely type formal French. They type Derja, and they type it
three different ways, often inside one sentence:

    Arabic script   عندي حبوب في وجهي
    Arabizi         3andi 7boub fi wajhi
    Code-switched   3andi des boutons w bachra dehnia

The language model handles the first form acceptably and the second poorly:
Arabizi is a transliteration convention, not a language, and the digit-letters
(3 = ع, 7 = ح, 9 = ق) are absent from most training data. Embedding models are
worse still, since "7boub" is simply an unknown token.

So this layer does the part a model does badly and rules do well: it recognises
Derja vocabulary — in either script — and maps it onto the controlled
vocabulary the engine already uses. Three consequences:

  1. /interpret and the agent receive French-equivalent hints alongside the
     original text, which sharply improves their accuracy.
  2. Semantic search embeds an enriched query, so Arabizi retrieves products
     whose descriptions are written in French.
  3. A Derja request still resolves to concerns when no language model is
     available at all, because the mapping is deterministic.

NOTE.— The lexicon below covers the beauty, hair and wellbeing vocabulary
observed in the client catalogue's domain. Derja has significant regional and
generational variation, and spelling in Arabizi is not standardised. It should
be reviewed and extended by a native speaker; the structure is designed so that
adding an entry is a one-line change.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# script detection
# ---------------------------------------------------------------------------

_ARABIC = re.compile(r"[\u0600-\u06FF]")
# Arabizi is Latin text carrying digit-letters inside words: "7boub", "3andi"
_ARABIZI = re.compile(r"\b\w*[2357899]\w*\b")


def detect_script(text: str) -> str:
    """Return 'arabic', 'arabizi', 'latin' or 'mixed'."""
    if not text:
        return "latin"
    has_arabic = bool(_ARABIC.search(text))
    # a bare number is not Arabizi; a digit glued to letters is
    has_arabizi = bool(re.search(r"[a-zA-Z][2357899]|[2357899][a-zA-Z]", text))
    if has_arabic and (has_arabizi or re.search(r"[a-zA-Z]{3}", text)):
        return "mixed"
    if has_arabic:
        return "arabic"
    if has_arabizi:
        return "arabizi"
    return "latin"


def _fold(text: str) -> str:
    """Lowercase, strip accents, normalise Arabic letter variants."""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Arabic orthographic variants that carry no meaning here
    text = (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                .replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و"))
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# lexicon
#
# Each entry maps a regular expression to (french_hint, vocabulary_value).
# The regex must match the FOLDED text, and should cover the Arabic-script
# spelling and the common Arabizi spellings of the same word.
# vocabulary_value is None when the term carries context but is not itself a
# concern (body part, product format, intensity).
# ---------------------------------------------------------------------------

CONCERNS = [
    # --- skin ---------------------------------------------------------------
    (r"7boub|7bub|7abaat|7aba|hboub|حبوب|بثور|بثرة",
     "boutons", "imperfections_acne"),
    (r"\bacne\b|3akne|\bboutons?\b|أكني|حب الشباب",
     "acné", "imperfections_acne"),
    (r"bo9a3|bq3|bouka3|bka3|بقع|كلف|تصبغات",
     "taches", "taches_pigmentaires"),
    (r"tajaa3id|tjaa3id|tajai3d|تجاعيد|خطوط",
     "rides", "rides_age"),
    (r"nachfa|nachef|nashef|na7fa|ناشف|ناشفة|جفاف|يابسة",
     "sèche", "deshydratation"),
    (r"dehni|dhini|dehnia|dhiniya|zayti|دهني|دهنية|زيتي",
     "grasse", "exces_sebum"),
    (r"7assas|7assasa|hassas|حساس|حساسة",
     "sensible", "rougeurs_sensibilite"),
    (r"7omra|7mira|احمرار|حمرة",
     "rougeurs", "rougeurs_sensibilite"),
    (r"7akka|7akkan|7ka|حكة|حكان",
     "démangeaisons", "rougeurs_sensibilite"),
    (r"chams|chems|شمس|حروق الشمس",
     "soleil", "protection_solaire"),
    (r"halat|hawalat|هالات|سواد تحت العين",
     "cernes", "cernes_poches"),
    (r"masamm|masam|مسام",
     "pores", "pores_dilates"),
    (r"baheta|bahta|kah?la|تعبانة|باهتة|شاحبة",
     "teint terne", "eclat_teint"),

    # --- hair ---------------------------------------------------------------
    (r"9echra|9ochra|kechra|قشرة|قشور",
     "pellicules", "pellicules"),
    (r"tay7an|ti7an|tay7in|yt?e?e?7|yat7|yti7|ytih|tsa9ot|"
     r"تساقط|طيحان|يطيح|يطيحو",
     "chute de cheveux", "chute_cheveux"),
    (r"mit9asef|mt9assef|mta3ab|متقصف|تقصف|متكسر",
     "cheveux abîmés", "cheveux_abimes"),

    # --- wellbeing ----------------------------------------------------------
    (r"ma nan3ass|nan3ess|no3ass|ar9|أرق|ما ننعسش|نوم",
     "sommeil", "sommeil_stress"),
    (r"stress|9al9|قلق|توتر|ضغط نفسي",
     "stress", "sommeil_stress"),
    (r"3ya|3yeit|3yen|تعب|إرهاق|عياء",
     "fatigue", "energie_tonus"),
    (r"karchi|me3da|karch|كرشي|معدة|هضم|انتفاخ",
     "digestion", "digestion"),
    (r"mna3a|manaa3a|مناعة",
     "immunité", "immunite"),
    (r"tan7if|ri?jim|rejim|تنحيف|رجيم|وزن",
     "minceur", "minceur_detox"),
    (r"adafir|dhafer|أظافر|ضوافر",
     "ongles", "cheveux_peau_ongles"),
]

# terms that indicate the domain rather than a concern
DOMAINS = [
    (r"wajh|wejh|wjeh|وجه|وجهي", "visage", "visage"),
    (r"cha3r|sha3r|ch3ar|شعر|شعري", "cheveux", "cheveux"),
    (r"bachra|bashra|beshra|بشرة|بشرتي|jelda|جلد", "peau", "visage"),
    (r"jesd|jism|جسم|بدن", "corps", "corps"),
    (r"chfayef|chfef|شفايف|شفة", "lèvres", "visage"),
    (r"3ine?ya|3ayn|عين|عيون", "yeux", "visage"),
]

# skin-type terms (overlap with concerns on purpose: "dehni" is both)
SKIN_TYPES = [
    (r"dehni|dhini|dehnia|zayti|دهني|دهنية", "grasse", "grasse"),
    (r"nachfa|nachef|nashef|ناشف|ناشفة|جافة", "sèche", "seche"),
    (r"7assas|7assasa|hassas|حساس|حساسة", "sensible", "sensible"),
    (r"mokhtalta|makhluta|mixte|مختلطة|مشتركة", "mixte", "mixte"),
    (r"3adiya|3adia|عادية", "normale", "normale"),
]

# useful context words with no vocabulary value of their own
MODIFIERS = [
    (r"barcha|barsha|yaser|ياسر|برشا", "beaucoup"),
    (r"chwaya|chwiya|شوية", "un peu"),
    (r"9dim|9dima|قديم|قديمة", "ancien"),
    (r"jdid|jdida|جديد|جديدة", "nouveau"),
    (r"rkhis|rkhiss|رخيص", "pas cher"),
    (r"ghali|8ali|غالي", "cher"),
    (r"\b3andi\b|عندي", "j'ai"),
    (r"n7eb|nheb|نحب|نبغي", "je veux"),
    (r"\bfamma\b|فما", "il y a"),
]


def _compile(entries):
    return [(re.compile(pat), *rest) for pat, *rest in entries]


_C_CONCERNS = _compile(CONCERNS)
_C_DOMAINS = _compile(DOMAINS)
_C_SKIN = _compile(SKIN_TYPES)
_C_MODS = _compile(MODIFIERS)


# ---------------------------------------------------------------------------
# public interface
# ---------------------------------------------------------------------------

def analyse(text: str) -> dict:
    """Extract everything recognisable from a Derja or Arabizi sentence.

    Returns the detected script, the French hints found, and the controlled
    vocabulary values they map to. Nothing here depends on a language model,
    so it works when one is unavailable and improves accuracy when one is not.
    """
    folded = _fold(text)
    script = detect_script(text)

    concerns, hints, domain, skin_type = [], [], None, None

    for rx, hint, value in _C_DOMAINS:
        if rx.search(folded):
            domain = domain or value
            hints.append(hint)

    for rx, hint, value in _C_SKIN:
        if rx.search(folded):
            skin_type = skin_type or value
            hints.append(hint)

    for rx, hint, value in _C_CONCERNS:
        if rx.search(folded):
            if value not in concerns:
                concerns.append(value)
            hints.append(hint)

    for rx, hint in _C_MODS:
        if rx.search(folded):
            hints.append(hint)

    # dedupe, preserving order
    seen, ordered = set(), []
    for h in hints:
        if h not in seen:
            seen.add(h)
            ordered.append(h)

    return {
        "script": script,
        "is_derja": script in ("arabic", "arabizi", "mixed") or bool(ordered),
        "hints": ordered,
        "concerns": concerns[:3],
        "domain": domain,
        "skin_type": skin_type,
    }


def enrich_query(text: str) -> str:
    """Append French equivalents to a query before embedding it.

    Product descriptions are written in French. An Arabizi query shares no
    tokens with them, so similarity collapses. Appending the recognised French
    terms gives the embedding something to match against, while keeping the
    original words in case the model does know them.
    """
    a = analyse(text)
    if not a["hints"]:
        return text
    return f"{text} — {', '.join(a['hints'])}"


# IPA and academic transliteration symbols a model may reach for instead of
# the digit convention people actually type. Nobody writes "nʕa9lek" in a chat.
IPA_TO_ARABIZI = {
    "ʕ": "3", "ʿ": "3", "ᶜ": "3",
    "ħ": "7", "ḥ": "7", "ẖ": "7",
    "ʔ": "2", "ʼ": "2", "ʾ": "2",
    "ɣ": "gh", "ġ": "gh",
    "χ": "kh", "ḫ": "kh", "x̣": "kh",
    "ṣ": "s", "ṭ": "t", "ḍ": "d", "ẓ": "z", "ṯ": "th", "ḏ": "dh",
    "ā": "a", "ī": "i", "ū": "ou",
}

# Internal vocabulary tokens must never reach a customer. If the model echoes
# one, show the label a shopper would recognise instead.
TOKEN_LABELS = {
    "taches_pigmentaires": "taches", "rides_age": "rides",
    "deshydratation": "hydratation", "imperfections_acne": "imperfections",
    "rougeurs_sensibilite": "rougeurs", "exces_sebum": "exces de sebum",
    "eclat_teint": "eclat du teint", "protection_solaire": "protection solaire",
    "cernes_poches": "cernes", "pores_dilates": "pores dilates",
    "chute_cheveux": "chute de cheveux", "cheveux_abimes": "cheveux abimes",
    "minceur_detox": "minceur", "sommeil_stress": "sommeil",
    "energie_tonus": "energie", "memoire_concentration": "memoire",
    "glycemie_tension": "glycemie", "sport_nutrition": "sport",
    "cheveux_peau_ongles": "cheveux, peau et ongles",
    "complement_oral": "complement", "routine_step": "etape",
    "boucles_frises": "boucles",
}

_IPA_RX = re.compile("|".join(map(re.escape, IPA_TO_ARABIZI)))
_TOKEN_RX = re.compile(r"\b(" + "|".join(map(re.escape, TOKEN_LABELS)) + r")\b")


def clean_reply(text: str) -> str:
    """Tidy a generated reply before it reaches the customer.

    Prompt instructions reduce these artefacts but do not eliminate them, and
    both are visible mistakes rather than stylistic ones: a shopper cannot read
    an IPA symbol, and an internal identifier looks like a bug.
    """
    if not text:
        return text
    text = _IPA_RX.sub(lambda m: IPA_TO_ARABIZI[m.group(0)], text)
    text = _TOKEN_RX.sub(lambda m: TOKEN_LABELS[m.group(1)], text)
    return text


def prompt_guidance(script: str = "latin") -> str:
    """Instructions for the language model, adapted to how the customer writes.

    UNDERSTANDING Derja and GENERATING it are very different problems. A model
    reads "3andi 7boub" correctly because context carries it, but writing back
    in Arabizi produces malformed Derja — the convention barely exists in
    training data, so the model guesses at morphology and produces word salad
    like "t3arraf t3arraf 3la n3a9lek".

    So the reply language is chosen by what the model can actually do well:

        Arabic script in  ->  reply in Arabic
        Arabizi / French  ->  reply in French

    This is not a downgrade. Arabizi is how Tunisians type, not a language they
    need read back to them, and French is the language of the product
    catalogue itself. Answering a "3andi 7boub" question in clear French is
    better service than answering it in broken Derja.
    """
    common = (
        "LANGUE : le client peut ecrire en francais, en arabe tunisien (derja) "
        "ou en arabizi (chiffres-lettres : 3=ain, 7=ha, 9=qaf, 5=kha). "
        "Comprends les trois.\n"
        "Exemples : 3andi 7boub = j'ai des boutons | bachra dehnia = peau grasse "
        "| cha3ri ytee7 = mes cheveux tombent | 9echra = pellicules | "
        "ma nan3assh = je dors mal | bo9a3 = taches.\n"
        "N'ecris JAMAIS les identifiants internes (taches_pigmentaires, "
        "exces_sebum...) : utilise les mots normaux."
    )

    if script == "arabic":
        return common + (
            "\nLe client ecrit en arabe : REPONDS EN ARABE, simplement et "
            "clairement. Garde les noms de produits tels quels."
        )

    return common + (
        "\nREPONDS TOUJOURS EN FRANCAIS, meme si le client ecrit en arabizi. "
        "N'ecris jamais ta reponse en arabizi : tu la formules mal. "
        "Francais simple et chaleureux."
    )
