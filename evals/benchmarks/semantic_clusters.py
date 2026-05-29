"""
Semantic robustness benchmarks (Phase 3).

Each cluster is a set of semantically equivalent query variants.
The eval verifies that ShopSense recommends similar products for all variants.
A high semantic consistency score means query phrasing doesn't flip rankings.
"""

from __future__ import annotations
from evals.benchmarks.base import SemanticCluster, RubricWeight, ProductProfile
from evals.benchmarks.users import _P, _rubric


def _srw(overrides: dict[str, float]) -> list[RubricWeight]:
    return _rubric(overrides)


SEMANTIC_CLUSTERS: list[SemanticCluster] = [
    SemanticCluster(
        id="gym_earbuds",
        name="Gym Earbuds Cluster",
        description="All variants should recommend sport-focused earbuds with secure fit",
        variants=[
            "earbuds for gym",
            "earbuds for workouts",
            "earbuds that won't fall out during exercise",
            "stable fit earbuds for running",
            "sweat-proof earbuds",
            "workout earbuds that stay in",
            "best earbuds for exercise",
        ],
        expected_top_products=["AthleteFit G5", "MidRange M7"],
        rubric_weights=_srw({
            "comfort": 9, "water_resistance": 9, "durability": 9,
            "battery_life": 8, "price_to_value": 6, "sound_quality": 5,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="anc_travel",
        name="Travel ANC Cluster",
        description="All variants should recommend high-ANC earbuds for travel",
        variants=[
            "earbuds for flights",
            "best earbuds for airplane travel",
            "noise cancelling earbuds for travel",
            "earbuds for blocking airplane noise",
            "travel earbuds with ANC",
            "noise isolating earbuds for commute",
            "earbuds to block out noise while traveling",
        ],
        expected_top_products=["PremiumPro A9", "WorkComfort W2"],
        rubric_weights=_srw({
            "noise_cancellation": 10, "battery_life": 9, "comfort": 8,
            "portability": 7, "sound_quality": 6, "price_to_value": 4,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="office_calls",
        name="Office / Calls Cluster",
        description="All variants should recommend call-quality earbuds",
        variants=[
            "earbuds for work calls",
            "best earbuds for Zoom meetings",
            "earbuds with good microphone",
            "work from home earbuds",
            "earbuds for video conferencing",
            "best earbuds for online meetings",
            "earbuds for conference calls",
        ],
        expected_top_products=["WorkComfort W2", "MidRange M7"],
        rubric_weights=_srw({
            "call_quality": 10, "microphone_quality": 10, "noise_cancellation": 8,
            "comfort": 8, "battery_life": 7, "price_to_value": 5,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="budget_earbuds",
        name="Budget Earbuds Cluster",
        description="All variants should recommend value-focused earbuds",
        variants=[
            "cheap earbuds",
            "best budget earbuds",
            "affordable wireless earbuds",
            "earbuds under ₹3000",
            "earbuds under $30",
            "value for money earbuds",
            "inexpensive earbuds that work well",
        ],
        expected_top_products=["BudgetBuds X3", "CompactBud C3"],
        rubric_weights=_srw({
            "price_to_value": 10, "durability": 7, "battery_life": 7,
            "sound_quality": 5, "comfort": 5,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="gaming_earbuds",
        name="Gaming Earbuds Cluster",
        description="All variants should recommend low-latency gaming earbuds",
        variants=[
            "earbuds for gaming",
            "low latency earbuds",
            "gaming wireless earbuds",
            "earbuds with gaming mode",
            "earbuds for FPS games",
            "best earbuds for mobile gaming",
            "earbuds with good mic for gaming",
        ],
        expected_top_products=["GamingEar Q4", "MidRange M7"],
        rubric_weights=_srw({
            "gaming_latency": 10, "microphone_quality": 8, "sound_quality": 7,
            "comfort": 7, "bass_response": 7, "price_to_value": 6,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="audiophile_sound",
        name="Audiophile Sound Quality Cluster",
        description="All variants should recommend reference-grade sound earbuds",
        variants=[
            "audiophile earbuds",
            "earbuds with best sound quality",
            "earbuds for music lovers",
            "high fidelity earbuds",
            "reference quality earbuds",
            "studio quality earbuds",
            "earbuds with balanced sound",
        ],
        expected_top_products=["AudioPhile H1", "PremiumPro A9"],
        rubric_weights=_srw({
            "sound_quality": 10, "bass_response": 8, "comfort": 7,
            "noise_cancellation": 4, "price_to_value": 3,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="portable_small",
        name="Portable / Small Earbuds Cluster",
        description="All variants should recommend compact portable earbuds",
        variants=[
            "most portable earbuds",
            "smallest earbuds",
            "compact wireless earbuds",
            "earbuds for travel with tiny case",
            "lightweight earbuds",
            "earbuds for small ears",
            "earbuds with small footprint",
        ],
        expected_top_products=["CompactBud C3", "BudgetBuds X3"],
        rubric_weights=_srw({
            "portability": 10, "comfort": 9, "battery_life": 6,
            "price_to_value": 8, "durability": 6, "sound_quality": 5,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="long_battery",
        name="Long Battery Life Cluster",
        description="All variants should recommend earbuds with the longest battery",
        variants=[
            "earbuds with longest battery life",
            "all day earbuds",
            "earbuds that last all day",
            "earbuds with long playtime",
            "earbuds for long trips",
            "best battery earbuds",
            "earbuds that don't die",
        ],
        expected_top_products=["AthleteFit G5", "MidRange M7"],
        rubric_weights=_srw({
            "battery_life": 10, "comfort": 8, "sound_quality": 6,
            "price_to_value": 6, "portability": 6,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="comfort_wearability",
        name="Comfort & Wearability Cluster",
        description="All variants should recommend the most comfortable earbuds",
        variants=[
            "most comfortable earbuds",
            "earbuds that don't hurt",
            "earbuds for sensitive ears",
            "comfortable earbuds for all day",
            "earbuds that feel good",
            "earbuds for long wear",
            "earbuds without ear fatigue",
        ],
        expected_top_products=["AthleteFit G5", "CompactBud C3"],
        rubric_weights=_srw({
            "comfort": 10, "portability": 9, "battery_life": 7,
            "sound_quality": 5, "price_to_value": 6,
        }),
        products=list(_P.values()),
    ),

    SemanticCluster(
        id="premium_flagship",
        name="Premium / Flagship Cluster",
        description="All variants should recommend the premium earbuds",
        variants=[
            "best earbuds money can buy",
            "premium earbuds",
            "flagship earbuds",
            "top of the line earbuds",
            "best wireless earbuds overall",
            "most expensive earbuds",
            "earbuds with no compromises",
        ],
        expected_top_products=["PremiumPro A9", "AudioPhile H1"],
        rubric_weights=_srw({
            "sound_quality": 9, "noise_cancellation": 9, "comfort": 9,
            "call_quality": 8, "battery_life": 7, "price_to_value": 1,
        }),
        products=list(_P.values()),
    ),
]


def all_clusters() -> list[SemanticCluster]:
    return SEMANTIC_CLUSTERS
