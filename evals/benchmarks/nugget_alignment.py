"""
Nugget Alignment Benchmark.

Tests partial-credit scoring for human expert alignment.  Instead of a
binary "top-3 match or not", each judgment carries a set of *nuggets* —
specific insight claims about which products the expert considers notable.
Each nugget carries an explicit ``products_mentioned`` list so credit can
be computed deterministically without any text parsing.

Credit formula per nugget:
    For each product P listed in products_mentioned:
      - P in expert_top3 AND P in our_top3  → 1.0  (both agree: include)
      - P not in expert_top3 AND P not in our_top3 → 1.0  (both agree: exclude)
      - P in expert_top3 AND P not in our_top3      → 0.0  (engine misses expert pick)
      - P not in expert_top3 AND P in our_top3      → 0.5  (engine over-includes)
    nugget_credit = mean of per-product credits
    If products_mentioned is empty → 0.8  (generic insight, neutral partial credit)

Per-judgment score = mean of nugget credits × 100
Overall metric score = mean of per-judgment scores.

Five products, four criteria, five rubrics:
    Criteria: sound_quality, noise_cancellation, battery_life, value_for_money

    Products (scores):
        AlphaChoice:   sound=9, nc=8, battery=6, value=5
        BetaChoice:    sound=8, nc=7, battery=8, value=7
        GammaChoice:   sound=5, nc=6, battery=9, value=7
        DeltaChoice:   sound=4, nc=5, battery=5, value=9
        EpsilonChoice: sound=3, nc=3, battery=4, value=4

    Rubric 1 (audio-focused):  sound=9, nc=7, battery=4, value=3
        → top-3: AlphaChoice(176), BetaChoice(174), GammaChoice(144)

    Rubric 2 (balanced):       sound=6, nc=6, battery=6, value=6
        → top-3: BetaChoice(180), AlphaChoice(168), GammaChoice(162)

    Rubric 3 (anc-dominant):   nc=8, sound=5, battery=5, value=7
        → top-3: BetaChoice(185), AlphaChoice(174), GammaChoice(167)

    Rubric 4 (value-dominant): value=9, battery=6, nc=4, sound=3
        → top-3: BetaChoice(163), GammaChoice(156), DeltaChoice(143)

    Rubric 5 (battery):        battery=9, sound=4, nc=5, value=5
        → top-3: BetaChoice(174), GammaChoice(166), AlphaChoice(155)

Eight NuggetJudgments with pre-verified expected scores:
    NJ1 audio_fidelity_expert     — 100.0 (perfect engine-expert agreement)
    NJ2 battery_optimizer         — 100.0 (same products, different order)
    NJ3 balanced_partial_disagree — 50.0  (one miss, one over-include)
    NJ4 value_hunter              — 100.0 (same products, different order)
    NJ5 anc_specialist_partial    — 62.5  (one miss, one over-include, one agree exclude)
    NJ6 exclusion_precision       — 100.0 (nuggets are all about excluded products)
    NJ7 unusual_expert_picks      — 66.7  (expert picks one non-engine product)
    NJ8 no_product_mentions       — 80.0  (all nuggets have empty products_mentioned)

Overall expected score: (100+100+50+100+62.5+100+66.7+80)/8 = 82.4
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.benchmarks.base import ProductProfile, RubricWeight


# ── Core dataclasses ──────────────────────────────────────────────────────────

@dataclass
class Nugget:
    """
    A single insight claim from an expert judgment.

    ``products_mentioned`` must use EXACT product names from the associated
    NuggetJudgment.products list — no fuzzy matching or text parsing occurs.
    An empty list means the nugget is a generic observation not tied to any
    specific product, which receives neutral partial credit (0.8).
    """
    text: str
    products_mentioned: list[str] = field(default_factory=list)


@dataclass
class NuggetJudgment:
    """
    A human expert judgment expressed through a set of nuggets.

    Each nugget has an explicit products_mentioned list so credit can be
    computed deterministically without any text parsing.
    """
    id: str
    name: str
    query: str
    products: list[ProductProfile]
    rubric_weights: list[RubricWeight]
    expert_rank_1: str
    expert_rank_2: str
    expert_rank_3: str
    nuggets: list[Nugget]

    @property
    def n_nuggets(self) -> int:
        return len(self.nuggets)

    @property
    def expert_top3(self) -> set[str]:
        return {self.expert_rank_1, self.expert_rank_2, self.expert_rank_3}


# ── Criteria & labels ─────────────────────────────────────────────────────────

_CRITERIA = [
    "sound_quality",
    "noise_cancellation",
    "battery_life",
    "value_for_money",
]

_CRITERIA_LABELS: dict[str, str] = {
    "sound_quality":     "Sound Quality",
    "noise_cancellation": "Noise Cancellation",
    "battery_life":      "Battery Life",
    "value_for_money":   "Value for Money",
}


# ── Product pool ──────────────────────────────────────────────────────────────
#
# Five products, four criteria.  Integer scores to keep weighted totals exact
# and free of floating-point ambiguity.
#
# Quality ranking under balanced rubric (all weights=6):
#   BetaChoice 180, AlphaChoice 168, GammaChoice 162, DeltaChoice 138, EpsilonChoice 84

_SCORES: dict[str, dict[str, float]] = {
    "AlphaChoice":   {"sound_quality": 9, "noise_cancellation": 8, "battery_life": 6, "value_for_money": 5},
    "BetaChoice":    {"sound_quality": 8, "noise_cancellation": 7, "battery_life": 8, "value_for_money": 7},
    "GammaChoice":   {"sound_quality": 5, "noise_cancellation": 6, "battery_life": 9, "value_for_money": 7},
    "DeltaChoice":   {"sound_quality": 4, "noise_cancellation": 5, "battery_life": 5, "value_for_money": 9},
    "EpsilonChoice": {"sound_quality": 3, "noise_cancellation": 3, "battery_life": 4, "value_for_money": 4},
}

_PRAISE: dict[str, list[str]] = {
    "AlphaChoice":   ["exceptional highs and mids", "class-leading noise cancellation"],
    "BetaChoice":    ["versatile all-day performer", "consistent across all criteria"],
    "GammaChoice":   ["outstanding battery endurance", "solid value proposition"],
    "DeltaChoice":   ["best budget pick", "excellent value for money"],
    "EpsilonChoice": ["ultra-affordable", "lightweight"],
}

_COMPLAINTS: dict[str, list[dict]] = {
    "AlphaChoice":   [{"text": "shorter battery life", "confidence": "high"}],
    "BetaChoice":    [{"text": "not the absolute best at any single criterion", "confidence": "medium"}],
    "GammaChoice":   [{"text": "sound quality below average", "confidence": "high"}],
    "DeltaChoice":   [{"text": "below-average sound and ANC", "confidence": "high"}],
    "EpsilonChoice": [{"text": "weak across all criteria", "confidence": "high"}],
}


def _make_product(name: str) -> ProductProfile:
    return ProductProfile(
        name=name,
        criterion_scores=dict(_SCORES[name]),
        signal_strength="strong",
        mention_count=30,
        positive_mentions=22,
        negative_mentions=8,
        praise=list(_PRAISE[name]),
        complaints=list(_COMPLAINTS[name]),
    )


_ALL_PRODUCTS: list[ProductProfile] = [_make_product(n) for n in _SCORES]


# ── Rubric builder ────────────────────────────────────────────────────────────

def _rubric(weights: dict[str, float]) -> list[RubricWeight]:
    return [
        RubricWeight(criterion=c, label=_CRITERIA_LABELS[c], weight=weights.get(c, 0.0))
        for c in _CRITERIA
    ]


# Five rubrics with pre-verified engine top-3 rankings:
#   Rubric 1 (audio):   [AlphaChoice(176), BetaChoice(174), GammaChoice(144)]
#   Rubric 2 (balanced):[BetaChoice(180),  AlphaChoice(168), GammaChoice(162)]
#   Rubric 3 (anc):     [BetaChoice(185),  AlphaChoice(174), GammaChoice(167)]
#   Rubric 4 (value):   [BetaChoice(163),  GammaChoice(156), DeltaChoice(143)]
#   Rubric 5 (battery): [BetaChoice(174),  GammaChoice(166), AlphaChoice(155)]
_RUBRIC_AUDIO    = _rubric({"sound_quality": 9, "noise_cancellation": 7, "battery_life": 4, "value_for_money": 3})
_RUBRIC_BALANCED = _rubric({"sound_quality": 6, "noise_cancellation": 6, "battery_life": 6, "value_for_money": 6})
_RUBRIC_ANC      = _rubric({"noise_cancellation": 8, "sound_quality": 5, "battery_life": 5, "value_for_money": 7})
_RUBRIC_VALUE    = _rubric({"value_for_money": 9, "battery_life": 6, "noise_cancellation": 4, "sound_quality": 3})
_RUBRIC_BATTERY  = _rubric({"battery_life": 9, "sound_quality": 4, "noise_cancellation": 5, "value_for_money": 5})


# ── NuggetJudgment definitions ────────────────────────────────────────────────

_JUDGMENTS: list[NuggetJudgment] = [

    # ── NJ1: perfect engine-expert agreement, audio-focused rubric ────────────
    # Engine top-3: [AlphaChoice, BetaChoice, GammaChoice]
    # Expert top-3: [AlphaChoice, BetaChoice, GammaChoice]
    # Nugget credits: 1.0, 1.0, 1.0  →  score = 100.0
    NuggetJudgment(
        id="nj_audio_fidelity_expert",
        name="Audio Fidelity Expert: Perfect Agreement",
        query="best earbuds for critical listening and audiophile use",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_AUDIO,
        expert_rank_1="AlphaChoice",
        expert_rank_2="BetaChoice",
        expert_rank_3="GammaChoice",
        nuggets=[
            Nugget(
                text="AlphaChoice and BetaChoice dominate for audiophile listening with the highest combined sound and ANC scores",
                products_mentioned=["AlphaChoice", "BetaChoice"],
            ),
            Nugget(
                text="GammaChoice rounds out the top-3 for audio-focused buyers despite its battery advantage going unused",
                products_mentioned=["GammaChoice"],
            ),
            Nugget(
                text="DeltaChoice and EpsilonChoice fall short on audio performance and are not recommended for this query",
                products_mentioned=["DeltaChoice", "EpsilonChoice"],
            ),
        ],
    ),

    # ── NJ2: same products, different expert order, battery rubric ────────────
    # Engine top-3: [BetaChoice(174), GammaChoice(166), AlphaChoice(155)]
    # Expert top-3: [GammaChoice, BetaChoice, AlphaChoice]  ← reordered
    # Nugget credits: 1.0, 1.0, 1.0  →  score = 100.0
    NuggetJudgment(
        id="nj_battery_optimizer",
        name="Battery Optimizer: Same Products, Different Order",
        query="earbuds with the longest battery life for travel",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_BATTERY,
        expert_rank_1="GammaChoice",
        expert_rank_2="BetaChoice",
        expert_rank_3="AlphaChoice",
        nuggets=[
            Nugget(
                text="GammaChoice and BetaChoice lead the field in battery endurance for long-haul travel",
                products_mentioned=["GammaChoice", "BetaChoice"],
            ),
            Nugget(
                text="DeltaChoice's battery is below average for its price tier",
                products_mentioned=["DeltaChoice"],
            ),
            Nugget(
                text="EpsilonChoice disappoints on battery and is not suitable for travel use",
                products_mentioned=["EpsilonChoice"],
            ),
        ],
    ),

    # ── NJ3: partial disagreement, balanced rubric ────────────────────────────
    # Engine top-3: [BetaChoice(180), AlphaChoice(168), GammaChoice(162)]
    # Expert top-3: [BetaChoice, AlphaChoice, DeltaChoice]  ← DeltaChoice instead of GammaChoice
    # Nugget credits:
    #   Nugget 1 [BetaChoice]  — both agree include → 1.0
    #   Nugget 2 [DeltaChoice] — expert in, engine miss → 0.0
    #   Nugget 3 [GammaChoice] — engine in, expert miss → 0.5
    # Score = (1.0 + 0.0 + 0.5) / 3 × 100 = 50.0
    NuggetJudgment(
        id="nj_balanced_partial_disagree",
        name="Balanced Rubric: Partial Expert-Engine Disagreement",
        query="well-rounded everyday earbuds for general use",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_BALANCED,
        expert_rank_1="BetaChoice",
        expert_rank_2="AlphaChoice",
        expert_rank_3="DeltaChoice",
        nuggets=[
            Nugget(
                text="BetaChoice is the consensus all-around champion with the highest balanced score",
                products_mentioned=["BetaChoice"],
            ),
            Nugget(
                text="DeltaChoice offers a compelling value proposition that makes it a top-3 pick for everyday use",
                products_mentioned=["DeltaChoice"],
            ),
            Nugget(
                text="GammaChoice has solid balanced performance and the engine ranks it third",
                products_mentioned=["GammaChoice"],
            ),
        ],
    ),

    # ── NJ4: value-focused, same products different order ─────────────────────
    # Engine top-3: [BetaChoice(163), GammaChoice(156), DeltaChoice(143)]
    # Expert top-3: [DeltaChoice, GammaChoice, BetaChoice]  ← value-focused reorder
    # Nugget credits: 1.0, 1.0, 1.0  →  score = 100.0
    NuggetJudgment(
        id="nj_value_hunter",
        name="Value Hunter: Same Products, Value-Focused Reorder",
        query="best bang-for-buck earbuds under budget",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_VALUE,
        expert_rank_1="DeltaChoice",
        expert_rank_2="GammaChoice",
        expert_rank_3="BetaChoice",
        nuggets=[
            Nugget(
                text="DeltaChoice and GammaChoice are the top value picks — high value_for_money and battery scores",
                products_mentioned=["DeltaChoice", "GammaChoice"],
            ),
            Nugget(
                text="AlphaChoice is overpriced relative to its value score and should not be recommended here",
                products_mentioned=["AlphaChoice"],
            ),
            Nugget(
                text="EpsilonChoice fails the cost-effectiveness test despite its low price",
                products_mentioned=["EpsilonChoice"],
            ),
        ],
    ),

    # ── NJ5: ANC-focused, partial disagreement ────────────────────────────────
    # Engine top-3: [BetaChoice(185), AlphaChoice(174), GammaChoice(167)]
    # Expert top-3: [AlphaChoice, BetaChoice, DeltaChoice]  ← DeltaChoice instead of GammaChoice
    # Nugget credits:
    #   Nugget 1 [AlphaChoice, BetaChoice] — both agree include → 1.0, 1.0 → 1.0
    #   Nugget 2 [DeltaChoice]             — expert in, engine miss → 0.0
    #   Nugget 3 [GammaChoice]             — engine in, expert miss → 0.5
    #   Nugget 4 [EpsilonChoice]           — both agree exclude → 1.0
    # Score = (1.0 + 0.0 + 0.5 + 1.0) / 4 × 100 = 62.5
    NuggetJudgment(
        id="nj_anc_specialist_partial",
        name="ANC Specialist: Partial Disagreement on Third Pick",
        query="earbuds with best noise cancellation for open-plan offices",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_ANC,
        expert_rank_1="AlphaChoice",
        expert_rank_2="BetaChoice",
        expert_rank_3="DeltaChoice",
        nuggets=[
            Nugget(
                text="AlphaChoice and BetaChoice are the undisputed ANC leaders for office environments",
                products_mentioned=["AlphaChoice", "BetaChoice"],
            ),
            Nugget(
                text="DeltaChoice's noise cancellation is underrated and warrants a top-3 recommendation",
                products_mentioned=["DeltaChoice"],
            ),
            Nugget(
                text="GammaChoice has decent but not exceptional ANC — the engine's third pick but not the expert's",
                products_mentioned=["GammaChoice"],
            ),
            Nugget(
                text="EpsilonChoice should be avoided entirely for ANC use cases due to weak noise cancellation",
                products_mentioned=["EpsilonChoice"],
            ),
        ],
    ),

    # ── NJ6: exclusion precision, audio rubric ────────────────────────────────
    # Engine top-3: [AlphaChoice, BetaChoice, GammaChoice]
    # Expert top-3: [AlphaChoice, BetaChoice, GammaChoice]
    # All nuggets mention products both expert and engine agree about
    # Nugget credits: 1.0, 1.0, 1.0  →  score = 100.0
    NuggetJudgment(
        id="nj_exclusion_precision",
        name="Exclusion Precision: Nuggets About Rejected Products",
        query="premium earbuds for audiophile listening sessions",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_AUDIO,
        expert_rank_1="AlphaChoice",
        expert_rank_2="BetaChoice",
        expert_rank_3="GammaChoice",
        nuggets=[
            Nugget(
                text="DeltaChoice is not suitable for audiophiles — weak sound quality limits its appeal",
                products_mentioned=["DeltaChoice"],
            ),
            Nugget(
                text="EpsilonChoice is unsuitable for audio-focused buyers in any tier",
                products_mentioned=["EpsilonChoice"],
            ),
            Nugget(
                text="AlphaChoice is the clear winner for pure audio fidelity use cases",
                products_mentioned=["AlphaChoice"],
            ),
        ],
    ),

    # ── NJ7: unusual expert picks, balanced rubric ────────────────────────────
    # Engine top-3: [BetaChoice(180), AlphaChoice(168), GammaChoice(162)]
    # Expert top-3: [BetaChoice, GammaChoice, EpsilonChoice]  ← EpsilonChoice unusual pick
    # Nugget credits:
    #   Nugget 1 [BetaChoice]    — both agree include → 1.0
    #   Nugget 2 [EpsilonChoice] — expert in, engine miss → 0.0
    #   Nugget 3 [GammaChoice]   — both agree include → 1.0
    # Score = (1.0 + 0.0 + 1.0) / 3 × 100 = 66.666... → 66.7
    NuggetJudgment(
        id="nj_unusual_expert_picks",
        name="Unusual Expert Picks: EpsilonChoice Surprise Selection",
        query="earbuds for casual listening with a unique aesthetic",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_BALANCED,
        expert_rank_1="BetaChoice",
        expert_rank_2="GammaChoice",
        expert_rank_3="EpsilonChoice",
        nuggets=[
            Nugget(
                text="BetaChoice is the consensus top pick regardless of use case",
                products_mentioned=["BetaChoice"],
            ),
            Nugget(
                text="EpsilonChoice has hidden intangibles — design and feel — that make it a surprise top-3 pick",
                products_mentioned=["EpsilonChoice"],
            ),
            Nugget(
                text="GammaChoice is a reliable middle-ground option for casual listeners",
                products_mentioned=["GammaChoice"],
            ),
        ],
    ),

    # ── NJ8: all nuggets have no product mentions → 0.8 per nugget ───────────
    # Engine top-3: [AlphaChoice, BetaChoice, GammaChoice] (audio rubric)
    # Expert top-3: [AlphaChoice, BetaChoice, GammaChoice]
    # Nugget credits: 0.8, 0.8, 0.8  →  score = 80.0
    NuggetJudgment(
        id="nj_no_product_mentions",
        name="No Product Mentions: Generic Expert Insights",
        query="earbuds for critical listening — general guidance",
        products=list(_ALL_PRODUCTS),
        rubric_weights=_RUBRIC_AUDIO,
        expert_rank_1="AlphaChoice",
        expert_rank_2="BetaChoice",
        expert_rank_3="GammaChoice",
        nuggets=[
            Nugget(
                text="Soundstage and detail retrieval are the primary differentiators in this category",
                products_mentioned=[],
            ),
            Nugget(
                text="Battery life is a secondary concern for home-based audiophile listening sessions",
                products_mentioned=[],
            ),
            Nugget(
                text="Build quality and cable management affect long-term durability across all products",
                products_mentioned=[],
            ),
        ],
    ),
]


# ── Public API ────────────────────────────────────────────────────────────────

def all_nugget_judgments() -> list[NuggetJudgment]:
    """Return all 8 nugget-based human judgments."""
    return list(_JUDGMENTS)
