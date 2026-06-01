"""
Per-comment sentiment analyser — Phase 3.

Two-stage pipeline:
  1. Rule-based pre-pass  — keyword-weighted scan in ±150-char windows around
     each product mention.  High-confidence results skip LLM entirely.
  2. LLM call             — only for products where rule-based returned ambiguous
     signal.  Flat output format {"Product": "positive"} cuts output tokens ~70%.

Zero LLM calls when all products resolve by rules.
One batched LLM call handles all remaining ambiguous products.
"""

import json
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Data model ─────────────────────────────────────────────────────────────────

# Bug 1: frozen=True prevents any caller from mutating a returned instance,
# making the shared _NEUTRAL_FALLBACK singleton safe to return everywhere.
@dataclass(frozen=True)
class SentimentScore:
    sentiment: str        # "positive" | "negative" | "neutral"
    source: str = "llm"   # "rule" | "llm" — preserved for debugging


_NEUTRAL_FALLBACK = SentimentScore(sentiment="neutral", source="llm")


# ── Optimized LLM system prompt ────────────────────────────────────────────────

# Changes vs original:
#  - Flat output format (no nested objects) → ~70% fewer output tokens
#  - "Include ALL listed products" closes the omission ambiguity
#  - Framed as purchase-signal, not generic sentiment
#  - Generic example product names (no domain bias)
#  - Single-pass regex recovery viable on flat format (Bug 2)
SENTIMENT_SYSTEM = """You are a sentiment classifier for a product research tool.
Given a Reddit comment and a list of products, classify whether the commenter
recommends, discourages, or is neutral about each product as a purchase.

Respond ONLY with a valid JSON object mapping each product name to exactly one of:
"positive", "negative", or "neutral"

Example: {"Product A": "positive", "Product B": "neutral"}

Rules:
- Use "positive" if the commenter recommends or endorses the product for purchase
- Use "negative" if the commenter discourages or criticizes it
- Use "neutral" if there is no clear purchase signal
- Include ALL listed products in your response, even if no clear opinion exists
- No markdown, no explanation, no extra keys — only the JSON object"""


# ── Rule-based pre-pass ────────────────────────────────────────────────────────

# Each tuple: (regex_pattern, weight).
# Higher weight = stronger, less ambiguous signal.
# Pre-compiled at module load — zero re-compilation cost during scoring.

_POS_PATTERNS: list[tuple[str, float]] = [
    (r"\bhighly recommend\b",                            3.0),
    (r"\bworth (every|the money|the price|it)\b",        3.0),
    (r"\bno complaints\b",                               3.0),
    (r"\bmust (buy|have|get)\b",                         3.0),
    (r"\b(bang for (the )?buck|value for money)\b",      2.5),
    (r"\b(best|great) (purchase|buy|decision)\b",        2.5),
    (r"\bwould (highly )?recommend\b",                   2.5),
    (r"\b(love|loved|loves|loving) (it|this|the)\b",     2.5),
    (r"\b(excellent|outstanding|phenomenal|superb|flawless)\b", 2.0),
    (r"\b(amazing|fantastic|awesome|brilliant)\b",       2.0),
    (r"\bworks (great|perfectly|well|flawlessly)\b",     2.0),
    (r"\b(satisfied|happy with|pleased with)\b",         2.0),
    (r"\b(great|perfect|impressive|impressed)\b",        1.5),
    (r"\b(solid|reliable|well.?built)\b",                1.0),
    (r"\bgood (value|buy|purchase|product)\b",           1.0),
    (r"\brecommended\b",                                 0.8),
    (r"\bgreat\b",                                       0.5),
    (r"\bgood\b",                                        0.3),
]

_NEG_PATTERNS: list[tuple[str, float]] = [
    (r"\b(avoid|stay away from|don.?t buy|do not buy)\b", 3.0),
    (r"\bwaste of money\b",                               3.0),
    (r"\bregret (buying|purchasing|getting)\b",           3.0),
    (r"\b(returning|returned) (it|this|mine)\b",          3.0),
    (r"\b(terrible|awful|horrible|atrocious)\b",          2.5),
    (r"\b(trash|garbage|junk|rubbish)\b",                 2.5),
    (r"\bnot worth (it|the money|the price)\b",           2.5),
    (r"\b(absolute )?worst\b",                            2.5),
    (r"\bfalls? short\b",                                 2.0),
    (r"\b(scam|fraud|fake)\b",                            2.0),
    (r"\b(broken|defective|dead on arrival|doa)\b",       2.0),
    (r"\b(disappointed|disappointing|disappointment)\b",  1.5),
    (r"\b(overpriced|way too expensive)\b",               1.5),
    (r"\b(flimsy|cheap (build|plastic|quality)|cheaply made)\b", 1.5),
    (r"\b(useless|pointless|worthless)\b",                1.5),
    (r"\bhate (it|this|the)\b",                           1.5),
    (r"\b(failed|failure|fails)\b",                       1.0),
    (r"\b(issues?|problems?)\b",                          0.4),
    (r"\bbad\b",                                          0.4),
]

_COMPILED_POS: list[tuple[re.Pattern, float]] = [
    (re.compile(p, re.IGNORECASE), w) for p, w in _POS_PATTERNS
]
_COMPILED_NEG: list[tuple[re.Pattern, float]] = [
    (re.compile(p, re.IGNORECASE), w) for p, w in _NEG_PATTERNS
]

# Net score must exceed this to accept a rule-based result.
# Keeps false-positive rate low — ambiguous comments fall through to LLM.
_RULE_THRESHOLD = 2.5


def _score_window(text: str) -> tuple[float, float]:
    """Return (positive_score, negative_score) for a text chunk."""
    pos = sum(w for pat, w in _COMPILED_POS if pat.search(text))
    neg = sum(w for pat, w in _COMPILED_NEG if pat.search(text))
    return pos, neg


def _rule_based_sentiment(text: str, product: str) -> str | None:
    """
    Score sentiment for `product` within `text` using keyword patterns.

    Scans ±150-char windows around each occurrence of the product name so that
    opinions about different products in the same comment don't bleed together.
    Falls back to full-text scoring when the product substring can't be located
    (e.g. matched via alias in Aho-Corasick but not exact string).

    Returns "positive" / "negative" if net score exceeds _RULE_THRESHOLD.
    Returns None for ambiguous cases — caller should invoke LLM.
    """
    text_lower = text.lower()
    prod_lower = product.lower()

    positions: list[int] = []
    search_from = 0
    while True:
        pos = text_lower.find(prod_lower, search_from)
        if pos < 0:
            break
        positions.append(pos)
        search_from = pos + 1

    if not positions:
        pos_score, neg_score = _score_window(text_lower)
    else:
        pos_score = neg_score = 0.0
        prod_len = len(prod_lower)
        for occurrence in positions:
            w_start = max(0, occurrence - 150)
            w_end = min(len(text_lower), occurrence + prod_len + 150)
            ps, ns = _score_window(text_lower[w_start:w_end])
            pos_score += ps
            neg_score += ns

    net = pos_score - neg_score
    if net >= _RULE_THRESHOLD:
        return "positive"
    if net <= -_RULE_THRESHOLD:
        return "negative"
    return None


# ── JSON parser ───────────────────────────────────────────────────────────────

# Bug 2 fix: flat-format regex recovery — extracts complete key:value pairs
# from truncated responses.  No iteration loop, no multi-close-brace guessing.
_FLAT_ENTRY_RE = re.compile(
    r'"([^"]+)"\s*:\s*"(positive|negative|neutral)"',
    re.IGNORECASE,
)


def _parse_sentiment_response(raw: str) -> dict:
    """
    Strip markdown fences and parse flat {"Product": "sentiment"} JSON.

    Bug 3 fix: handles uppercase ```JSON, leading newlines, inline fences via
    re.IGNORECASE + re.MULTILINE flags.

    Bug 2 fix: on JSONDecodeError, regex recovery extracts every complete
    product:sentiment pair from the truncated response — partial entries are
    ignored rather than guessed.

    Returns {} on total failure — never raises.
    """
    # Bug 3: strip fences regardless of case, leading newlines, or trailing whitespace
    cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", raw.strip(), flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Bug 2: regex-based partial recovery for truncated flat JSON
    recovered: dict[str, str] = {}
    for match in _FLAT_ENTRY_RE.finditer(cleaned):
        recovered[match.group(1)] = match.group(2).lower()

    if recovered:
        logger.debug("[sentiment_analyser] Partial JSON recovery: %d products", len(recovered))
    else:
        logger.warning("[sentiment_analyser] JSON parse failed entirely, raw: %.200s", raw)

    return recovered


def _coerce_score(raw_value, product_name: str) -> SentimentScore:
    """Validate a flat LLM value (string) and return a SentimentScore."""
    if isinstance(raw_value, str):
        s = raw_value.lower().strip()
        if s in {"positive", "negative", "neutral"}:
            return SentimentScore(sentiment=s, source="llm")
    logger.debug(
        "[sentiment_analyser] Unexpected value %r for %r — using neutral",
        raw_value, product_name,
    )
    return SentimentScore(sentiment="neutral", source="llm")


# ── Core function ─────────────────────────────────────────────────────────────

def analyse_comment(
    comment_text: str,
    products_in_comment: list[str],
    llm_client,
) -> dict[str, SentimentScore]:
    """
    Score sentiment for each product in a single Reddit comment.

    Pipeline:
      1. Rule-based pre-pass scores products with clear keyword signal.
      2. Only ambiguous products go to a single batched LLM call.
      3. If ALL products resolved by rules, no LLM call is made at all.

    On ANY failure, returns neutral fallback — never crashes.
    """
    if not products_in_comment:
        return {}

    if not comment_text or not comment_text.strip():
        return {p: _NEUTRAL_FALLBACK for p in products_in_comment}

    # Bug 5: log truncation so callers know opinion data may be incomplete
    comment_body = comment_text.strip()
    if len(comment_body) > 1500:
        logger.debug(
            "[sentiment_analyser] Comment truncated from %d to 1500 chars",
            len(comment_body),
        )
        comment_body = comment_body[:1500]

    # ── Stage 1: rule-based pre-pass ─────────────────────────────────────────
    results: dict[str, SentimentScore] = {}
    ambiguous: list[str] = []

    for product in products_in_comment:
        rule_result = _rule_based_sentiment(comment_body, product)
        if rule_result is not None:
            results[product] = SentimentScore(sentiment=rule_result, source="rule")
        else:
            ambiguous.append(product)

    if not ambiguous:
        logger.debug(
            "[sentiment_analyser] Rule-based resolved all %d products — LLM skipped",
            len(results),
        )
        return results

    # ── Stage 2: LLM call for ambiguous products only ────────────────────────
    product_list_str = "\n".join(f"- {p}" for p in ambiguous)

    prompt = (
        f"REDDIT COMMENT:\n{comment_body}\n\n"
        f"PRODUCTS TO SCORE:\n{product_list_str}\n\n"
        "Return a JSON object mapping each product name to its purchase sentiment."
    )

    try:
        raw = llm_client("sentiment_analyser", user_prompt=prompt, system=SENTIMENT_SYSTEM)
        parsed = _parse_sentiment_response(raw)

        for product in ambiguous:
            entry = parsed.get(product)
            if entry is None:
                # Case-insensitive fallback for LLMs that change capitalisation
                for key, val in parsed.items():
                    if key.lower() == product.lower():
                        entry = val
                        break
            results[product] = _coerce_score(entry, product) if entry is not None else _NEUTRAL_FALLBACK

    except Exception as exc:
        logger.warning("[sentiment_analyser] LLM call failed: %s", exc)
        for product in ambiguous:
            results[product] = _NEUTRAL_FALLBACK

    rule_count = len(products_in_comment) - len(ambiguous)
    if rule_count:
        logger.debug(
            "[sentiment_analyser] Rule: %d products, LLM: %d products",
            rule_count, len(ambiguous),
        )

    return results
