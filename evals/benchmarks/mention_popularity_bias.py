"""
Mention Popularity Bias Benchmark.

Tests that the scoring engine is immune to mention-count inflation — that
manipulating a product's mention_count, positive_mentions, or negative_mentions
does NOT change its weighted_total or rank.

Design:
  Five purpose-built products share five criteria.  Their criterion_scores are
  fixed; only the mention fields vary between baseline and biased variants.

  Quality ranking under the balanced rubric (all weights=8):
    1. QualityKing   (sound=9, value=8, battery=7, comfort=8, calls=8) → 320
    2. SolidSecond   (sound=8, value=7, battery=8, comfort=7, calls=8) → 304
    3. MidProduct    (sound=7, value=7, battery=7, comfort=7, calls=7) → 280
    4. WeakEntry     (sound=5, value=6, battery=5, comfort=6, calls=5) → 216
    5. PopularLow    (sound=3, value=4, battery=4, comfort=3, calls=3) → 136

  Ten bias scenarios:
    1. mention_inversion        — swap mentions of rank-1 and rank-5
    2. flood_loser              — give rank-5 one million mentions
    3. zero_winner_mentions     — zero out rank-1's mentions
    4. all_zero_mentions        — zero all products' mentions
    5. uniform_high_mentions    — all products get 999 mentions (identical)
    6. winner_starved           — rank-1 gets 1 mention; others get 500
    7. positive_flood_loser     — rank-5 gets 100 000 positive_mentions
    8. negative_flood_winner    — rank-1 gets 100 000 negative_mentions
    9. tail_coalition_boost     — ranks 4-5 each get 100 000 mentions
   10. sentiment_swap           — loser gets pure positive, winner gets pure negative

Three checks per scenario (weights 50 / 30 / 20):
    1. score_invariant (50 pts) — weighted_total is identical between baseline and biased
    2. rank1_stable    (30 pts) — rank-1 winner unchanged
    3. top3_stable     (20 pts) — full top-3 ordering unchanged

All checks are deterministic pure-Python arithmetic — no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.benchmarks.base import ProductProfile, RubricWeight


# ── BiasScenario dataclass ────────────────────────────────────────────────────

@dataclass
class BiasScenario:
    """
    A scenario that tests engine immunity to mention-count manipulation.

    Fields:
        baseline_products  — realistic mention counts, same criterion_scores
        biased_products    — manipulated mention counts, IDENTICAL criterion_scores
        rubric_weights     — scoring rubric (unchanged between baseline and biased)
        expected_rank_1    — quality-based winner (should be identical in both variants)
        expected_top_3     — quality-based top-3 (should be identical in both variants)
        bias_type          — short label for the manipulation applied
        bias_description   — human-readable description of what was changed
    """
    id: str
    name: str
    description: str
    tags: list[str]
    baseline_products: list[ProductProfile]
    biased_products: list[ProductProfile]
    rubric_weights: list[RubricWeight]
    expected_rank_1: str
    expected_top_3: list[str]
    bias_type: str
    bias_description: str = ""

    @property
    def n_products(self) -> int:
        return len(self.baseline_products)

    @property
    def biased_product_names(self) -> list[str]:
        return [p.name for p in self.biased_products]


# ── Product pool ──────────────────────────────────────────────────────────────

_CRITERIA = [
    "sound_quality",
    "value_for_money",
    "battery_life",
    "comfort",
    "call_quality",
]

_CRITERIA_LABELS: dict[str, str] = {
    "sound_quality": "Sound Quality",
    "value_for_money": "Value for Money",
    "battery_life": "Battery Life",
    "comfort": "Comfort & Fit",
    "call_quality": "Call Quality",
}

# Baseline mention counts: realistic distribution (higher-quality products
# tend to be discussed more, but quality and popularity can diverge in practice).
_BASELINE_MENTIONS: dict[str, tuple[int, int, int]] = {
    #                         mc   pos  neg
    "QualityKing": (45, 35, 10),
    "SolidSecond": (38, 28, 10),
    "MidProduct":  (28, 20,  8),
    "WeakEntry":   (15,  9,  6),
    "PopularLow":  ( 8,  5,  3),
}

# Criterion scores — IMMUTABLE across all scenarios (baseline and biased).
# Ranking under balanced rubric (all weights=8):
#   QualityKing 320, SolidSecond 304, MidProduct 280, WeakEntry 216, PopularLow 136.
_SCORES: dict[str, dict[str, float]] = {
    "QualityKing": {"sound_quality": 9, "value_for_money": 8, "battery_life": 7, "comfort": 8, "call_quality": 8},
    "SolidSecond": {"sound_quality": 8, "value_for_money": 7, "battery_life": 8, "comfort": 7, "call_quality": 8},
    "MidProduct":  {"sound_quality": 7, "value_for_money": 7, "battery_life": 7, "comfort": 7, "call_quality": 7},
    "WeakEntry":   {"sound_quality": 5, "value_for_money": 6, "battery_life": 5, "comfort": 6, "call_quality": 5},
    "PopularLow":  {"sound_quality": 3, "value_for_money": 4, "battery_life": 4, "comfort": 3, "call_quality": 3},
}

_PRAISE: dict[str, list[str]] = {
    "QualityKing": ["exceptional audio", "great build quality", "reliable daily driver"],
    "SolidSecond": ["consistent performance", "long battery life"],
    "MidProduct":  ["good value compromise", "decent all-round"],
    "WeakEntry":   ["budget friendly", "acceptable basics"],
    "PopularLow":  ["very affordable", "lightweight"],
}

_COMPLAINTS: dict[str, list[dict]] = {
    "QualityKing": [{"text": "premium price", "confidence": "medium"}],
    "SolidSecond": [{"text": "average mic", "confidence": "low"}],
    "MidProduct":  [{"text": "no standout feature", "confidence": "medium"}],
    "WeakEntry":   [{"text": "average sound", "confidence": "high"}, {"text": "weak bass", "confidence": "medium"}],
    "PopularLow":  [{"text": "poor noise cancellation", "confidence": "high"}, {"text": "tinny sound", "confidence": "high"}],
}


def _make_product(name: str, mc: int, pos: int, neg: int) -> ProductProfile:
    """Create a ProductProfile with given mention counts and fixed criterion_scores."""
    return ProductProfile(
        name=name,
        criterion_scores=dict(_SCORES[name]),
        signal_strength="strong" if mc >= 30 else "moderate" if mc >= 10 else "weak",
        mention_count=mc,
        positive_mentions=pos,
        negative_mentions=neg,
        praise=list(_PRAISE[name]),
        complaints=list(_COMPLAINTS[name]),
    )


def _baseline_products() -> list[ProductProfile]:
    """Return the five products with realistic baseline mention counts."""
    return [
        _make_product(name, mc, pos, neg)
        for name, (mc, pos, neg) in _BASELINE_MENTIONS.items()
    ]


def _biased(overrides: dict[str, tuple[int, int, int]]) -> list[ProductProfile]:
    """
    Build a biased product list.  Products not in `overrides` keep baseline counts.
    Criterion scores are NEVER changed.
    """
    return [
        _make_product(name, *overrides.get(name, baseline))
        for name, baseline in _BASELINE_MENTIONS.items()
    ]


# ── Rubric builder ────────────────────────────────────────────────────────────

def _rubric(weights: dict[str, float]) -> list[RubricWeight]:
    """Full 5-criterion rubric; missing criteria get weight=0.0."""
    return [
        RubricWeight(criterion=c, label=_CRITERIA_LABELS[c], weight=weights.get(c, 0.0))
        for c in _CRITERIA
    ]


_BALANCED_RUBRIC = _rubric({c: 8.0 for c in _CRITERIA})

# ── Scenario definitions ──────────────────────────────────────────────────────
# Expected quality ranking (all scenarios share the same criterion_scores):
#   rank-1: QualityKing
#   rank-2: SolidSecond
#   rank-3: MidProduct
_EXPECTED_RANK_1 = "QualityKing"
_EXPECTED_TOP_3 = ["QualityKing", "SolidSecond", "MidProduct"]

_SCENARIOS: list[BiasScenario] = [
    # S1 — swap rank-1 and rank-5 mention counts
    BiasScenario(
        id="bias_mention_inversion",
        name="Mention Count Inversion: Quality Leader vs Popularity Leader",
        description=(
            "QualityKing's 45 mentions and PopularLow's 8 mentions are swapped. "
            "The lowest-quality product now appears most-discussed."
        ),
        tags=["inversion", "rank1", "rank5"],
        baseline_products=_baseline_products(),
        biased_products=_biased({
            "QualityKing": (8, 5, 3),
            "PopularLow":  (45, 35, 10),
        }),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="inversion",
        bias_description="Swapped QualityKing (45→8) and PopularLow (8→45) mention counts.",
    ),

    # S2 — flood lowest-quality product with 1 million mentions
    BiasScenario(
        id="bias_flood_loser",
        name="Popularity Flood: One Million Mentions on Lowest-Quality Product",
        description=(
            "PopularLow receives 1 000 000 mentions — 22 000× its baseline. "
            "QualityKing retains its superior criterion scores."
        ),
        tags=["flood", "extreme", "rank5"],
        baseline_products=_baseline_products(),
        biased_products=_biased({"PopularLow": (1_000_000, 800_000, 200_000)}),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="mention_flood",
        bias_description="PopularLow mention_count inflated from 8 to 1 000 000.",
    ),

    # S3 — zero out rank-1's mentions
    BiasScenario(
        id="bias_zero_winner_mentions",
        name="Silence the Winner: QualityKing Gets Zero Mentions",
        description=(
            "QualityKing's mention count is set to zero — as if it were never discussed. "
            "All other products retain their baseline mentions."
        ),
        tags=["zero-mentions", "rank1", "silence"],
        baseline_products=_baseline_products(),
        biased_products=_biased({"QualityKing": (0, 0, 0)}),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="mention_zero",
        bias_description="QualityKing mention_count zeroed (45→0).",
    ),

    # S4 — zero all mentions
    BiasScenario(
        id="bias_all_zero_mentions",
        name="Total Silence: All Products Get Zero Mentions",
        description=(
            "Every product's mention count, positive_mentions, and negative_mentions "
            "are set to zero. Pure quality-based ranking should be unaffected."
        ),
        tags=["zero-mentions", "all-products", "silence"],
        baseline_products=_baseline_products(),
        biased_products=_biased({name: (0, 0, 0) for name in _BASELINE_MENTIONS}),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="all_zero",
        bias_description="All products zeroed: mention_count=0, positive_mentions=0, negative_mentions=0.",
    ),

    # S5 — uniform high mentions
    BiasScenario(
        id="bias_uniform_high_mentions",
        name="Uniform Popularity: All Products Get 999 Mentions",
        description=(
            "Every product receives the same high mention count (999). "
            "A mention-count-dependent ranker would be confused; a pure quality "
            "ranker is unaffected."
        ),
        tags=["uniform", "high-mentions", "all-products"],
        baseline_products=_baseline_products(),
        biased_products=_biased({name: (999, 750, 249) for name in _BASELINE_MENTIONS}),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="uniform_high",
        bias_description="All products assigned identical mention_count=999.",
    ),

    # S6 — winner starved, rest boosted
    BiasScenario(
        id="bias_winner_starved",
        name="Winner Starved: QualityKing Gets 1 Mention, Others Get 500",
        description=(
            "QualityKing is given only 1 mention while every other product "
            "receives 500. The highest-quality product is the least-mentioned."
        ),
        tags=["starved", "boost-others", "rank1"],
        baseline_products=_baseline_products(),
        biased_products=_biased({
            "QualityKing": (1, 1, 0),
            "SolidSecond": (500, 400, 100),
            "MidProduct":  (500, 380, 120),
            "WeakEntry":   (500, 300, 200),
            "PopularLow":  (500, 280, 220),
        }),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="winner_starved",
        bias_description="QualityKing: 1 mention; all others: 500 mentions.",
    ),

    # S7 — flood lowest-quality's positive_mentions
    BiasScenario(
        id="bias_positive_flood_loser",
        name="Sentiment Flood: PopularLow Gets 100 000 Positive Mentions",
        description=(
            "PopularLow receives 100 000 positive_mentions and 0 negative — "
            "a perfect artificial sentiment score. Criterion quality is unchanged."
        ),
        tags=["sentiment", "positive-flood", "rank5"],
        baseline_products=_baseline_products(),
        biased_products=_biased({"PopularLow": (100_000, 100_000, 0)}),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="positive_flood",
        bias_description="PopularLow positive_mentions inflated to 100 000 (negative_mentions=0).",
    ),

    # S8 — flood winner's negative_mentions
    BiasScenario(
        id="bias_negative_flood_winner",
        name="Negative Flood: QualityKing Gets 100 000 Negative Mentions",
        description=(
            "QualityKing receives 100 000 negative_mentions — a devastated sentiment "
            "ratio. Its criterion scores remain identical."
        ),
        tags=["sentiment", "negative-flood", "rank1"],
        baseline_products=_baseline_products(),
        biased_products=_biased({"QualityKing": (100_000, 0, 100_000)}),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="negative_flood",
        bias_description="QualityKing negative_mentions inflated to 100 000 (positive_mentions=0).",
    ),

    # S9 — tail products (ranks 4-5) get coalition boost
    BiasScenario(
        id="bias_tail_coalition_boost",
        name="Tail Coalition: WeakEntry and PopularLow Each Get 100 000 Mentions",
        description=(
            "The two weakest products each receive 100 000 mentions, dwarfing the "
            "top products' baseline counts. A popularity-biased engine would promote "
            "them; the eval engine must not."
        ),
        tags=["coalition", "tail-boost", "rank4", "rank5"],
        baseline_products=_baseline_products(),
        biased_products=_biased({
            "WeakEntry":  (100_000, 70_000, 30_000),
            "PopularLow": (100_000, 60_000, 40_000),
        }),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="tail_coalition",
        bias_description="WeakEntry and PopularLow each inflated to 100 000 mentions.",
    ),

    # S10 — complete sentiment inversion
    BiasScenario(
        id="bias_sentiment_swap",
        name="Sentiment Swap: Loser Gets Pure Positive, Winner Gets Pure Negative",
        description=(
            "PopularLow: positive_mentions=100 000, negative_mentions=0 (perfect sentiment). "
            "QualityKing: positive_mentions=0, negative_mentions=100 000 (worst sentiment). "
            "Criterion quality determines the winner, not sentiment."
        ),
        tags=["sentiment", "swap", "extreme"],
        baseline_products=_baseline_products(),
        biased_products=_biased({
            "QualityKing": (100_000, 0, 100_000),
            "PopularLow":  (100_000, 100_000, 0),
        }),
        rubric_weights=_BALANCED_RUBRIC,
        expected_rank_1=_EXPECTED_RANK_1,
        expected_top_3=_EXPECTED_TOP_3,
        bias_type="sentiment_swap",
        bias_description=(
            "QualityKing: pos=0, neg=100 000. PopularLow: pos=100 000, neg=0."
        ),
    ),
]


# ── Public API ────────────────────────────────────────────────────────────────

def all_bias_scenarios() -> list[BiasScenario]:
    """Return all 10 mention popularity bias scenarios."""
    return list(_SCENARIOS)
