"""
Phase 8: Review ranking engine.

Computes a composite review_rank_score (0.0–1.0) per review:
  trust_score          × 0.40
  freshness_score      × 0.25
  content_quality      × 0.20
  retrieval_confidence × 0.15

content_quality is derived from content length and structure signals (no LLM).

Usage: rank first, then select. Never filter aggressively on score alone.
"""

from __future__ import annotations


def compute_review_rank_score(
    trust_score: float,
    freshness_score: float,
    content: str,
    retrieval_confidence: float = 0.80,
) -> float:
    """
    Compute composite ranking score 0.0–1.0 for a single review.

    retrieval_confidence default 0.80 = high confidence (Gemini grounding).
    Adjust downward for Serper-fallback results.
    """
    cq = _content_quality(content)
    raw = (
        trust_score          * 0.40
        + freshness_score    * 0.25
        + cq                 * 0.20
        + retrieval_confidence * 0.15
    )
    return round(min(1.0, max(0.0, raw)), 3)


def rank_reviews(reviews: list[dict]) -> list[dict]:
    """Sort reviews by review_rank_score descending. Reviews without a score go last."""
    return sorted(reviews, key=lambda r: r.get("review_rank_score", 0.0), reverse=True)


# ---------------------------------------------------------------------------
# Content quality heuristic
# ---------------------------------------------------------------------------

_QUALITY_KEYWORDS = {
    "battery", "display", "performance", "processor", "camera", "sound",
    "build", "verdict", "pros", "cons", "conclusion", "benchmark",
    "test", "measurement", "review", "compared", "versus",
}

_METRIC_SIGNALS = ["%", "/10", "mm", "hours", "nits", "hz", "watts", "ghz", "gb", "ms"]


def _content_quality(content: str) -> float:
    if not content:
        return 0.0

    length = len(content)

    # Length score: < 300 chars is too thin; 2K–8K is ideal; > 8K has diminishing returns
    if length < 300:
        length_score = 0.15
    elif length < 1_000:
        length_score = 0.45
    elif length < 3_000:
        length_score = 0.70
    elif length <= 8_000:
        length_score = 1.00
    else:
        length_score = 0.88  # very long: likely noisy

    # Metric density: presence of measurements/specs
    text_lower = content.lower()
    metric_hits = sum(1 for s in _METRIC_SIGNALS if s in text_lower)
    metric_score = min(metric_hits / 5.0, 1.0)

    # Keyword diversity: review vocabulary coverage
    kw_hits = sum(1 for kw in _QUALITY_KEYWORDS if kw in text_lower)
    kw_score = min(kw_hits / 5.0, 1.0)

    score = 0.60 * length_score + 0.25 * metric_score + 0.15 * kw_score
    return round(min(1.0, score), 3)
