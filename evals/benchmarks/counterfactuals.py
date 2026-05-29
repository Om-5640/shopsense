"""
Counterfactual sensitivity benchmarks (Phase 5).

Each pair modifies EXACTLY ONE variable (one rubric weight) and verifies
that the ranking changes in the expected direction. If changing a criterion
weight doesn't affect the ranking, the system is insensitive to that attribute.
"""

from __future__ import annotations
from evals.benchmarks.base import CounterfactualPair, RubricWeight
from evals.benchmarks.users import _P, _rubric


def _rw(overrides: dict[str, float]) -> list[RubricWeight]:
    return _rubric(overrides)


_PRODUCTS = list(_P.values())


COUNTERFACTUAL_PAIRS: list[CounterfactualPair] = [
    # Budget: price importance low → high
    CounterfactualPair(
        id="cf_budget_low_vs_high",
        name="Budget — Price Unimportant vs. Critical",
        description="When price becomes critical, BudgetBuds should rise to rank 1",
        changed_criterion="price_to_value",
        base_rubric=_rw({
            "price_to_value": 1, "sound_quality": 3, "noise_cancellation": 3,
            "comfort": 3, "battery_life": 3,
        }),
        modified_rubric=_rw({
            "price_to_value": 10, "sound_quality": 3, "noise_cancellation": 3,
            "comfort": 3, "battery_life": 3,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="BudgetBuds X3",
    ),

    # ANC: low importance → high importance
    CounterfactualPair(
        id="cf_anc_low_vs_high",
        name="ANC — Unimportant vs. Critical",
        description="Raising ANC weight should move PremiumPro/WorkComfort to rank 1",
        changed_criterion="noise_cancellation",
        base_rubric=_rw({
            "noise_cancellation": 1, "sound_quality": 8, "battery_life": 8,
            "comfort": 8, "price_to_value": 7,
        }),
        modified_rubric=_rw({
            "noise_cancellation": 10, "sound_quality": 8, "battery_life": 8,
            "comfort": 8, "price_to_value": 7,
        }),
        products=_PRODUCTS,
        base_winner="MidRange M7",
        modified_winner="PremiumPro A9",
    ),

    # Water resistance: not important → critical (gym user)
    CounterfactualPair(
        id="cf_water_low_vs_high",
        name="Water Resistance — Unimportant vs. Critical",
        description="When water resistance matters, AthleteFit should dominate",
        changed_criterion="water_resistance",
        base_rubric=_rw({
            "water_resistance": 1, "sound_quality": 7, "battery_life": 7,
            "price_to_value": 8, "connectivity": 7,
        }),
        modified_rubric=_rw({
            "water_resistance": 10, "sound_quality": 7, "battery_life": 7,
            "price_to_value": 8, "connectivity": 7,
        }),
        products=_PRODUCTS,
        base_winner="MidRange M7",
        modified_winner="AthleteFit G5",
    ),

    # Gaming latency: not important → critical
    CounterfactualPair(
        id="cf_latency_low_vs_high",
        name="Gaming Latency — Unimportant vs. Critical",
        description="Raising gaming latency weight should move GamingEar to rank 1",
        changed_criterion="gaming_latency",
        base_rubric=_rw({
            "gaming_latency": 1, "sound_quality": 7, "battery_life": 7,
            "price_to_value": 8, "connectivity": 7,
        }),
        modified_rubric=_rw({
            "gaming_latency": 10, "sound_quality": 7, "battery_life": 7,
            "price_to_value": 8, "connectivity": 7,
        }),
        products=_PRODUCTS,
        base_winner="MidRange M7",
        modified_winner="GamingEar Q4",
    ),

    # Microphone: not important → critical
    CounterfactualPair(
        id="cf_mic_low_vs_high",
        name="Microphone — Unimportant vs. Critical",
        description="When mic quality becomes critical, WorkComfort/GamingEar should rise",
        changed_criterion="microphone_quality",
        base_rubric=_rw({
            "microphone_quality": 1, "sound_quality": 8, "battery_life": 8,
            "comfort": 8, "price_to_value": 7,
        }),
        modified_rubric=_rw({
            "microphone_quality": 10, "sound_quality": 8, "battery_life": 8,
            "comfort": 8, "price_to_value": 7,
        }),
        products=_PRODUCTS,
        base_winner="MidRange M7",
        modified_winner="WorkComfort W2",
    ),

    # Battery: not important → very important
    CounterfactualPair(
        id="cf_battery_low_vs_high",
        name="Battery Life — Unimportant vs. Critical",
        description="When battery is critical, AthleteFit (battery=9) should rise",
        changed_criterion="battery_life",
        base_rubric=_rw({
            "battery_life": 1, "sound_quality": 3, "noise_cancellation": 3,
            "comfort": 3,
        }),
        modified_rubric=_rw({
            "battery_life": 10, "sound_quality": 3, "noise_cancellation": 3,
            "comfort": 3,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="AthleteFit G5",
    ),

    # Comfort: not important → very important
    CounterfactualPair(
        id="cf_comfort_low_vs_high",
        name="Comfort — Unimportant vs. Critical",
        description="When comfort is critical, AthleteFit or CompactBud should rise",
        changed_criterion="comfort",
        base_rubric=_rw({
            "comfort": 1, "sound_quality": 4, "noise_cancellation": 1,
            "battery_life": 4,
        }),
        modified_rubric=_rw({
            "comfort": 10, "sound_quality": 4, "noise_cancellation": 1,
            "battery_life": 4,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="AthleteFit G5",
    ),

    # Portability: low → high
    CounterfactualPair(
        id="cf_portability_low_vs_high",
        name="Portability — Unimportant vs. Critical",
        description="When portability is critical, CompactBud should rise",
        changed_criterion="portability",
        base_rubric=_rw({
            "portability": 1, "sound_quality": 4, "noise_cancellation": 4,
            "comfort": 4, "price_to_value": 4,
        }),
        modified_rubric=_rw({
            "portability": 10, "sound_quality": 4, "noise_cancellation": 4,
            "comfort": 4, "price_to_value": 4,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="CompactBud C3",
    ),

    # Ecosystem integration: not important → critical (Apple user)
    CounterfactualPair(
        id="cf_ecosystem_low_vs_high",
        name="Ecosystem Integration — Unimportant vs. Critical",
        description="When ecosystem matters (Apple user), PremiumPro should dominate",
        changed_criterion="ecosystem_integration",
        base_rubric=_rw({
            "ecosystem_integration": 1, "sound_quality": 6, "connectivity": 6,
            "price_to_value": 8, "battery_life": 6,
        }),
        modified_rubric=_rw({
            "ecosystem_integration": 10, "sound_quality": 6, "connectivity": 6,
            "price_to_value": 8, "battery_life": 6,
        }),
        products=_PRODUCTS,
        base_winner="MidRange M7",
        modified_winner="PremiumPro A9",
    ),

    # Sound quality: low → high
    CounterfactualPair(
        id="cf_sound_low_vs_high",
        name="Sound Quality — Unimportant vs. Critical",
        description="When sound quality is critical, AudioPhile/PremiumPro should rise",
        changed_criterion="sound_quality",
        base_rubric=_rw({
            "sound_quality": 1, "noise_cancellation": 7, "comfort": 7,
            "battery_life": 8, "portability": 6,
        }),
        modified_rubric=_rw({
            "sound_quality": 10, "noise_cancellation": 7, "comfort": 7,
            "battery_life": 8, "portability": 6,
        }),
        products=_PRODUCTS,
        base_winner="AthleteFit G5",
        modified_winner="PremiumPro A9",
    ),

    # Bass response: low → high
    CounterfactualPair(
        id="cf_bass_low_vs_high",
        name="Bass Response — Unimportant vs. Critical",
        description="When bass is critical, AudioPhile H1 or GamingEar should win",
        changed_criterion="bass_response",
        base_rubric=_rw({
            "bass_response": 1, "sound_quality": 6, "noise_cancellation": 3,
            "connectivity": 3,
        }),
        modified_rubric=_rw({
            "bass_response": 10, "sound_quality": 6, "noise_cancellation": 3,
            "connectivity": 3,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="AudioPhile H1",
    ),

    # Call quality: low → high
    CounterfactualPair(
        id="cf_call_quality_low_vs_high",
        name="Call Quality — Unimportant vs. Critical",
        description="When call quality becomes critical, WorkComfort should rise",
        changed_criterion="call_quality",
        base_rubric=_rw({
            "call_quality": 1, "sound_quality": 3, "noise_cancellation": 2,
            "comfort": 4,
        }),
        modified_rubric=_rw({
            "call_quality": 10, "sound_quality": 3, "noise_cancellation": 2,
            "comfort": 4,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="WorkComfort W2",
    ),

    # Durability: low → high
    CounterfactualPair(
        id="cf_durability_low_vs_high",
        name="Durability — Unimportant vs. Critical",
        description="When durability is critical, AthleteFit or BudgetBuds should rise",
        changed_criterion="durability",
        base_rubric=_rw({
            "durability": 1, "sound_quality": 3, "noise_cancellation": 2,
            "comfort": 3,
        }),
        modified_rubric=_rw({
            "durability": 10, "sound_quality": 3, "noise_cancellation": 2,
            "comfort": 3,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="AthleteFit G5",
    ),

    # Transparency: low → high
    CounterfactualPair(
        id="cf_transparency_low_vs_high",
        name="Transparency Mode — Unimportant vs. Critical",
        description="When transparency is critical (cyclists), PremiumPro rises",
        changed_criterion="transparency_mode",
        base_rubric=_rw({
            "transparency_mode": 1, "sound_quality": 8, "battery_life": 8,
            "comfort": 8, "price_to_value": 7,
        }),
        modified_rubric=_rw({
            "transparency_mode": 10, "sound_quality": 8, "battery_life": 8,
            "comfort": 8, "price_to_value": 7,
        }),
        products=_PRODUCTS,
        base_winner="MidRange M7",
        modified_winner="PremiumPro A9",
    ),

    # Connectivity: low → high
    CounterfactualPair(
        id="cf_connectivity_low_vs_high",
        name="Bluetooth Connectivity — Unimportant vs. Critical",
        description="When multipoint/stability is critical, MidRange/PremiumPro rise",
        changed_criterion="connectivity",
        base_rubric=_rw({
            "connectivity": 1, "sound_quality": 8, "noise_cancellation": 7,
            "ecosystem_integration": 6,
        }),
        modified_rubric=_rw({
            "connectivity": 10, "sound_quality": 8, "noise_cancellation": 7,
            "ecosystem_integration": 6,
        }),
        products=_PRODUCTS,
        base_winner="PremiumPro A9",
        modified_winner="PremiumPro A9",
        must_differ=False,  # PremiumPro has connectivity=9 in both cases — acceptable stable
    ),
]


def all_counterfactuals() -> list[CounterfactualPair]:
    return COUNTERFACTUAL_PAIRS
