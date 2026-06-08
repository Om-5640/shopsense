"""
Conflict Detection Benchmark.

Tests the scoring engine's behaviour when two criteria that a user cares about
equally (or near-equally) point to different products — a "genuine conflict".

Design:
  Six purpose-built products share the same five criteria:
    • Five specialist products: score=9 on one criterion, score=4 on all others.
    • One all-rounder (MidRange): score=7 on every criterion.

  Key arithmetic invariant:
    specialist:  9 + 4 = 13   (sum across two conflicting criteria × equal weight)
    mid-range:   7 + 7 = 14   (sum across same two criteria × equal weight)

  Consequence: under EQUAL criterion weights, MidRange always beats any pair of
  competing specialists.  Under EXTREME single-criterion weights, the relevant
  specialist always beats MidRange (9 > 7 on that one criterion).

  Ten conflict scenarios are defined across all pairings:
    • 7 equal-weight pairings  → MidRange wins the balanced rubric
    • 2 unequal-weight pairings → a specialist wins (demonstrates weight sensitivity)
    • 1 three-way equal conflict → MidRange still wins

Three checks per scenario (weights: 40 / 30 / 30):
    1. rank_correct       — engine picks expected_balanced_winner under balanced rubric
    2. primary_wins       — primary_champion wins when only primary_criterion has weight
    3. secondary_wins     — secondary_champion wins when only secondary_criterion has weight

All checks are deterministic pure-Python arithmetic — no LLM calls required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.benchmarks.base import ProductProfile, RubricWeight


# ── ConflictScenario dataclass ────────────────────────────────────────────────

@dataclass
class ConflictScenario:
    """
    A scenario where two criteria the user values pull in different directions.

    Fields:
        id / name / description / tags — identity and metadata
        products          — shared pool of ProductProfile objects
        rubric_weights    — the "balanced conflict" rubric (all 5 criteria present,
                            with 0.0 weight for inactive ones)
        expected_balanced_winner  — product that wins under the balanced rubric
        primary_criterion   — criterion A of the conflict (used to find primary_champion)
        secondary_criterion — criterion B of the conflict (used to find secondary_champion)
        primary_champion    — product that wins when ONLY primary_criterion has weight
        secondary_champion  — product that wins when ONLY secondary_criterion has weight
        conflict_description — human-readable explanation of the tradeoff
    """
    id: str
    name: str
    description: str
    tags: list[str]
    products: list[ProductProfile]
    rubric_weights: list[RubricWeight]
    expected_balanced_winner: str
    primary_criterion: str
    secondary_criterion: str
    primary_champion: str
    secondary_champion: str
    conflict_description: str = ""

    @property
    def genuine_conflict(self) -> bool:
        """True when primary and secondary champions are different products."""
        return self.primary_champion != self.secondary_champion


# ── Product pool ──────────────────────────────────────────────────────────────

_CRITERIA = [
    "sound_quality",
    "price_to_value",
    "battery_life",
    "comfort",
    "call_quality",
]

_CRITERIA_LABELS: dict[str, str] = {
    "sound_quality":  "Sound Quality",
    "price_to_value": "Price to Value",
    "battery_life":   "Battery Life",
    "comfort":        "Comfort & Fit",
    "call_quality":   "Call Quality",
}

# Five specialists + one all-rounder.
# Specialists score 9 on their domain, 4 on all others.
# MidRange scores 7 on everything.
# Invariant: 7+7=14 > 9+4=13, so MidRange beats specialist pairs under equal weights.
_P: list[ProductProfile] = [
    ProductProfile(
        name="SoundKing",
        criterion_scores={
            "sound_quality": 9, "price_to_value": 4, "battery_life": 4,
            "comfort": 4, "call_quality": 4,
        },
        signal_strength="strong",
        mention_count=55, positive_mentions=44, negative_mentions=11,
        praise=["exceptional audio detail", "wide soundstage", "deep controlled bass"],
        complaints=[
            {"text": "expensive relative to battery life", "confidence": "high"},
            {"text": "limited call microphone performance", "confidence": "medium"},
        ],
    ),
    ProductProfile(
        name="PricePick",
        criterion_scores={
            "sound_quality": 4, "price_to_value": 9, "battery_life": 4,
            "comfort": 4, "call_quality": 4,
        },
        signal_strength="moderate",
        mention_count=42, positive_mentions=33, negative_mentions=9,
        praise=["unbeatable value for money", "affordable entry point"],
        complaints=[
            {"text": "average sound signature", "confidence": "high"},
            {"text": "decent but not premium build", "confidence": "medium"},
        ],
    ),
    ProductProfile(
        name="BatteryAce",
        criterion_scores={
            "sound_quality": 4, "price_to_value": 4, "battery_life": 9,
            "comfort": 4, "call_quality": 4,
        },
        signal_strength="moderate",
        mention_count=38, positive_mentions=29, negative_mentions=9,
        praise=["all-week battery endurance", "50+ hours total playtime"],
        complaints=[
            {"text": "mediocre audio fidelity", "confidence": "high"},
            {"text": "microphone limited on calls", "confidence": "medium"},
        ],
    ),
    ProductProfile(
        name="CallPro",
        criterion_scores={
            "sound_quality": 4, "price_to_value": 4, "battery_life": 4,
            "comfort": 4, "call_quality": 9,
        },
        signal_strength="moderate",
        mention_count=45, positive_mentions=36, negative_mentions=9,
        praise=["crystal-clear voice pickup", "six-mic beam-forming array"],
        complaints=[
            {"text": "average music playback quality", "confidence": "high"},
            {"text": "battery life below average", "confidence": "medium"},
        ],
    ),
    ProductProfile(
        name="ComfortPlus",
        criterion_scores={
            "sound_quality": 4, "price_to_value": 4, "battery_life": 4,
            "comfort": 9, "call_quality": 4,
        },
        signal_strength="moderate",
        mention_count=33, positive_mentions=25, negative_mentions=8,
        praise=["cloud-like fit", "zero ear fatigue after ten hours"],
        complaints=[
            {"text": "below-average audio fidelity", "confidence": "high"},
            {"text": "noise isolation weaker than rivals", "confidence": "medium"},
        ],
    ),
    ProductProfile(
        name="MidRange",
        criterion_scores={
            "sound_quality": 7, "price_to_value": 7, "battery_life": 7,
            "comfort": 7, "call_quality": 7,
        },
        signal_strength="strong",
        mention_count=68, positive_mentions=52, negative_mentions=16,
        praise=["reliable daily driver", "consistent across all areas", "no obvious weaknesses"],
        complaints=[
            {"text": "not best-in-class at any single feature", "confidence": "medium"},
            {"text": "lacks a standout signature feature", "confidence": "low"},
        ],
    ),
]


# ── Rubric builder ────────────────────────────────────────────────────────────

def _rubric(weights: dict[str, float]) -> list[RubricWeight]:
    """
    Build a full 5-criterion RubricWeight list.
    Criteria absent from `weights` receive weight=0.0 so they don't influence
    scores but keep the rubric structurally complete for extreme-rubric derivation.
    """
    return [
        RubricWeight(
            criterion=c,
            label=_CRITERIA_LABELS[c],
            weight=weights.get(c, 0.0),
        )
        for c in _CRITERIA
    ]


# ── Scenario definitions ──────────────────────────────────────────────────────
#
# Per-scenario math verification (balanced rubric only; scores = weighted_total):
#
# S1  sound=8, price=8:     SoundKing=104 PricePick=104  MidRange=112 ← wins
# S2  sound=8, battery=8:   SoundKing=104 BatteryAce=104 MidRange=112 ← wins
# S3  sound=8, calls=8:     SoundKing=104 CallPro=104    MidRange=112 ← wins
# S4  price=8, battery=8:   PricePick=104 BatteryAce=104 MidRange=112 ← wins
# S5  price=8, calls=8:     PricePick=104 CallPro=104    MidRange=112 ← wins
# S6  battery=8, calls=8:   BatteryAce=104 CallPro=104   MidRange=112 ← wins
# S7  snd=7, prc=7, bat=7:  SoundKing=BatteryAce=PricePick=119 MidRange=147 ← wins
# S8  sound=9, price=5:     SoundKing=101 MidRange=98            ← SoundKing wins
# S9  battery=9, comfort=5: BatteryAce=101 MidRange=98           ← BatteryAce wins
# S10 calls=8, comfort=8:   CallPro=104 ComfortPlus=104 MidRange=112 ← wins

_SCENARIOS: list[ConflictScenario] = [
    ConflictScenario(
        id="conflict_sound_vs_price",
        name="Sound Quality vs Price — Equal Tradeoff",
        description=(
            "User wants best sound AND best value equally. "
            "No product excels at both; a balanced choice wins."
        ),
        tags=["sound", "price", "conflict", "equal-weight"],
        products=_P,
        rubric_weights=_rubric({"sound_quality": 8, "price_to_value": 8}),
        expected_balanced_winner="MidRange",
        primary_criterion="sound_quality",
        secondary_criterion="price_to_value",
        primary_champion="SoundKing",
        secondary_champion="PricePick",
        conflict_description=(
            "SoundKing (sound=9, price=4) and PricePick (sound=4, price=9) each "
            "score 9×8+4×8=104. MidRange (7,7) scores 7×8+7×8=112 — the balanced "
            "product wins because 7+7=14 > 9+4=13 under equal weights."
        ),
    ),
    ConflictScenario(
        id="conflict_sound_vs_battery",
        name="Sound Quality vs Battery Life — Equal Tradeoff",
        description=(
            "User wants great audio AND long battery equally. "
            "Audiophile products sacrifice battery; high-battery products sacrifice sound."
        ),
        tags=["sound", "battery", "conflict", "equal-weight"],
        products=_P,
        rubric_weights=_rubric({"sound_quality": 8, "battery_life": 8}),
        expected_balanced_winner="MidRange",
        primary_criterion="sound_quality",
        secondary_criterion="battery_life",
        primary_champion="SoundKing",
        secondary_champion="BatteryAce",
        conflict_description=(
            "SoundKing and BatteryAce each score 104; MidRange scores 112. "
            "Neither specialist wins when both criteria are equally weighted."
        ),
    ),
    ConflictScenario(
        id="conflict_sound_vs_calls",
        name="Music Quality vs Call Quality — Equal Tradeoff",
        description=(
            "User wants earbuds optimised for music AND calls equally — "
            "two very different engineering targets."
        ),
        tags=["sound", "calls", "conflict", "equal-weight"],
        products=_P,
        rubric_weights=_rubric({"sound_quality": 8, "call_quality": 8}),
        expected_balanced_winner="MidRange",
        primary_criterion="sound_quality",
        secondary_criterion="call_quality",
        primary_champion="SoundKing",
        secondary_champion="CallPro",
        conflict_description=(
            "Audio-tuned products sacrifice mic quality; call-focused products have "
            "constrained sound signatures. MidRange navigates the tradeoff."
        ),
    ),
    ConflictScenario(
        id="conflict_price_vs_battery",
        name="Price to Value vs Battery Life — Equal Tradeoff",
        description=(
            "User wants cheap AND long-lasting equally. "
            "Ultra-budget options cut battery to reduce cost."
        ),
        tags=["price", "battery", "conflict", "equal-weight"],
        products=_P,
        rubric_weights=_rubric({"price_to_value": 8, "battery_life": 8}),
        expected_balanced_winner="MidRange",
        primary_criterion="price_to_value",
        secondary_criterion="battery_life",
        primary_champion="PricePick",
        secondary_champion="BatteryAce",
        conflict_description=(
            "Cheapest option has short battery; longest-battery option costs more. "
            "MidRange avoids both compromises."
        ),
    ),
    ConflictScenario(
        id="conflict_price_vs_calls",
        name="Price to Value vs Call Quality — Equal Tradeoff",
        description=(
            "User wants affordable AND business-grade call quality — "
            "a classic consumer-vs-enterprise conflict."
        ),
        tags=["price", "calls", "conflict", "equal-weight"],
        products=_P,
        rubric_weights=_rubric({"price_to_value": 8, "call_quality": 8}),
        expected_balanced_winner="MidRange",
        primary_criterion="price_to_value",
        secondary_criterion="call_quality",
        primary_champion="PricePick",
        secondary_champion="CallPro",
        conflict_description=(
            "Budget earbuds cut corners on the microphone array; "
            "premium-mic earbuds carry a business-grade price premium."
        ),
    ),
    ConflictScenario(
        id="conflict_battery_vs_calls",
        name="Battery Life vs Call Quality — Equal Tradeoff",
        description=(
            "User wants long battery for all-day use AND great call quality for meetings — "
            "power optimisation vs microphone engineering."
        ),
        tags=["battery", "calls", "conflict", "equal-weight"],
        products=_P,
        rubric_weights=_rubric({"battery_life": 8, "call_quality": 8}),
        expected_balanced_winner="MidRange",
        primary_criterion="battery_life",
        secondary_criterion="call_quality",
        primary_champion="BatteryAce",
        secondary_champion="CallPro",
        conflict_description=(
            "BatteryAce sacrifices mic quality; CallPro sacrifices battery. "
            "MidRange provides reliable balance across both."
        ),
    ),
    ConflictScenario(
        id="conflict_three_way_sound_price_battery",
        name="Three-Way Conflict: Sound × Price × Battery",
        description=(
            "User equally values sound quality, value and battery life — "
            "three competing engineering priorities."
        ),
        tags=["sound", "price", "battery", "conflict", "three-way"],
        products=_P,
        rubric_weights=_rubric({"sound_quality": 7, "price_to_value": 7, "battery_life": 7}),
        expected_balanced_winner="MidRange",
        primary_criterion="sound_quality",
        secondary_criterion="price_to_value",
        primary_champion="SoundKing",
        secondary_champion="PricePick",
        conflict_description=(
            "SoundKing, PricePick and BatteryAce all score 7×(9+4+4)=119; "
            "MidRange scores 7×(7+7+7)=147 — four times above all specialists."
        ),
    ),
    ConflictScenario(
        id="conflict_sound_dominant",
        name="Sound-Dominant Rubric — Specialist Wins",
        description=(
            "User heavily prioritises sound (weight=9) with minor price preference (weight=5). "
            "The sound specialist wins; MidRange cannot overcome the weight asymmetry."
        ),
        tags=["sound", "price", "specialist-wins", "unequal-weight"],
        products=_P,
        rubric_weights=_rubric({"sound_quality": 9, "price_to_value": 5}),
        expected_balanced_winner="SoundKing",
        primary_criterion="sound_quality",
        secondary_criterion="price_to_value",
        primary_champion="SoundKing",
        secondary_champion="PricePick",
        conflict_description=(
            "SoundKing: 9×9+4×5=101; MidRange: 7×9+7×5=98. "
            "Weight ratio 9:5 > 4:3 threshold — SoundKing beats MidRange."
        ),
    ),
    ConflictScenario(
        id="conflict_battery_dominant",
        name="Battery-Dominant Rubric — Specialist Wins",
        description=(
            "User heavily prioritises battery life (weight=9) with minor comfort preference (weight=5). "
            "The battery specialist wins decisively."
        ),
        tags=["battery", "comfort", "specialist-wins", "unequal-weight"],
        products=_P,
        rubric_weights=_rubric({"battery_life": 9, "comfort": 5}),
        expected_balanced_winner="BatteryAce",
        primary_criterion="battery_life",
        secondary_criterion="comfort",
        primary_champion="BatteryAce",
        secondary_champion="ComfortPlus",
        conflict_description=(
            "BatteryAce: 9×9+4×5=101; MidRange: 7×9+7×5=98. "
            "Battery criterion's higher weight gives BatteryAce the edge."
        ),
    ),
    ConflictScenario(
        id="conflict_calls_vs_comfort",
        name="Call Quality vs Comfort — Equal Tradeoff",
        description=(
            "User wants great call quality AND comfortable all-day fit equally. "
            "Call-optimised earbuds trade comfort for mic seal; comfort-first designs affect pickup."
        ),
        tags=["calls", "comfort", "conflict", "equal-weight"],
        products=_P,
        rubric_weights=_rubric({"call_quality": 8, "comfort": 8}),
        expected_balanced_winner="MidRange",
        primary_criterion="call_quality",
        secondary_criterion="comfort",
        primary_champion="CallPro",
        secondary_champion="ComfortPlus",
        conflict_description=(
            "CallPro and ComfortPlus each score 104; MidRange scores 112. "
            "Tight-seal mics reduce comfort; soft comfort tips reduce mic seal."
        ),
    ),
]


# ── Public API ────────────────────────────────────────────────────────────────

def all_conflict_scenarios() -> list[ConflictScenario]:
    """Return all 10 hand-crafted conflict scenarios."""
    return list(_SCENARIOS)
