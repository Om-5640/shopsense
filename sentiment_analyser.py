"""
Per-comment sentiment analyser — Phase 3.

Called ONLY for comments where at least one product mention was confirmed
by the Aho-Corasick scanner.  Zero LLM calls for unmentioned comments.

One LLM call handles ALL products found in the same comment simultaneously,
keeping call budget proportional to confirmed-mention comments (not total comments).
"""

import json
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class SentimentScore:
    sentiment: str    # exactly "positive" | "negative" | "neutral"
    confidence: float  # 0.0 to 1.0
    reason: str        # one sentence


_NEUTRAL_FALLBACK = SentimentScore(sentiment="neutral", confidence=0.5, reason="No sentiment data")


# ── LLM system prompt (exact as specified) ────────────────────────────────────

SENTIMENT_SYSTEM = """You are a sentiment analyser for a product research tool.
Given a Reddit comment and the products mentioned in it, score the sentiment
expressed toward EACH product.

Respond ONLY with valid JSON. No markdown, no explanation, no backticks.
{
  "Realme Buds Air 7": {
    "sentiment": "positive",
    "confidence": 0.92,
    "reason": "User praises battery life and calls it best value for money"
  }
}

Rules:
- sentiment: exactly one of positive, negative, neutral
- confidence: 0.0 to 1.0
- reason: one sentence, your own words
- No clear opinion expressed? Return neutral, confidence 0.5
- Only include products actually discussed with opinion in this comment"""


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse_sentiment_response(raw: str) -> dict:
    """
    Strip markdown fences and parse JSON from LLM response.
    Returns {} on any failure — never raises.
    """
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
        return {}
    except json.JSONDecodeError:
        pass

    # Walk backwards to find a parseable truncation
    for cut in range(len(cleaned) - 1, max(len(cleaned) - 200, 0), -1):
        candidate = cleaned[:cut].rstrip().rstrip(",")
        try:
            result = json.loads(candidate + "}")
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue

    return {}


def _coerce_score(raw_entry: dict, product_name: str) -> SentimentScore:
    """
    Coerce a raw LLM entry into a valid SentimentScore.
    Sanitizes sentiment to one of the three allowed values.
    Clamps confidence to [0.0, 1.0].
    """
    if not isinstance(raw_entry, dict):
        return _NEUTRAL_FALLBACK

    sentiment = str(raw_entry.get("sentiment", "neutral")).lower().strip()
    if sentiment not in {"positive", "negative", "neutral"}:
        sentiment = "neutral"

    try:
        confidence = float(raw_entry.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    reason = str(raw_entry.get("reason", "")).strip()
    if not reason:
        reason = f"No reason provided for {product_name}"

    return SentimentScore(sentiment=sentiment, confidence=confidence, reason=reason)


# ── Core function ─────────────────────────────────────────────────────────────

def analyse_comment(
    comment_text: str,
    products_in_comment: list[str],
    llm_client,
) -> dict[str, SentimentScore]:
    """
    Score sentiment for each product in a single Reddit comment.

    One LLM call covers ALL products simultaneously — efficient batch analysis.
    On ANY failure, returns neutral fallback for every product — never crashes.

    Args:
        comment_text       : the raw comment body
        products_in_comment: canonical names confirmed present by Aho-Corasick
        llm_client         : callable matching run_agent(agent_name, user_prompt, system)

    Returns:
        { canonical_name: SentimentScore }
    """
    if not products_in_comment:
        return {}

    if not comment_text or not comment_text.strip():
        return {p: _NEUTRAL_FALLBACK for p in products_in_comment}

    product_list_str = "\n".join(f"- {p}" for p in products_in_comment)

    prompt = (
        f"REDDIT COMMENT:\n{comment_text.strip()[:1500]}\n\n"
        f"PRODUCTS TO SCORE:\n{product_list_str}\n\n"
        f"Score the sentiment expressed toward each product in this comment."
    )

    try:
        raw = llm_client("sentiment_analyser", user_prompt=prompt, system=SENTIMENT_SYSTEM)
        parsed = _parse_sentiment_response(raw)

        results: dict[str, SentimentScore] = {}

        for product in products_in_comment:
            # Try exact match first, then case-insensitive
            entry = parsed.get(product)
            if entry is None:
                for key, val in parsed.items():
                    if key.lower() == product.lower():
                        entry = val
                        break

            if entry is not None:
                results[product] = _coerce_score(entry, product)
            else:
                # Product not in response — neutral fallback
                results[product] = _NEUTRAL_FALLBACK

        return results

    except Exception as exc:
        logger.warning("[sentiment_analyser] LLM call failed: %s", exc)
        return {p: _NEUTRAL_FALLBACK for p in products_in_comment}
