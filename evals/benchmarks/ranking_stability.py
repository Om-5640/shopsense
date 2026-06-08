"""
Fix 19: Ranking Stability Benchmark.

Provides StabilityScenario dataclasses + scenario fixtures for the
RankingStabilityMetric.  Each scenario carries a set of products and a
base rubric; the metric applies ±10% Gaussian weight perturbations and
measures whether the ranking stays stable (Spearman ρ ≥ threshold).

These scenarios are designed to cover:
  - A well-separated field (rank-1 clear leader → very stable)
  - A tightly-clustered field (razor-thin margins → expected instability)
  - A mid-range field (mixed separations)
  - Weight edge cases (single criterion, many criteria)
  - Category diversity (earbuds, laptops, smartphones, mattresses)
"""

from __future__ import annotations
from dataclasses import dataclass, field

from evals.benchmarks.base import ProductProfile, RubricWeight


@dataclass
class StabilityScenario:
    id: str
    description: str
    category: str
    products: list[ProductProfile]
    base_rubric: list[RubricWeight]
    # Minimum acceptable mean Spearman ρ across perturbations (0.0–1.0)
    min_spearman: float = 0.70
    tags: list[str] = field(default_factory=list)


def all_stability_scenarios() -> list[StabilityScenario]:
    return [
        # ── sc-001: Clear winner — should be nearly perfectly stable ──────────
        StabilityScenario(
            id="sc-001",
            description="Earbuds with a clear leader (3-pt+ margins) — high stability expected",
            category="electronics/earbuds",
            products=[
                ProductProfile(
                    name="SoundPro Elite",
                    criterion_scores={"sound_quality": 9.5, "noise_cancellation": 9.0, "battery_life": 8.5, "value": 7.0},
                    signal_strength="high",
                ),
                ProductProfile(
                    name="Budget Buds",
                    criterion_scores={"sound_quality": 6.0, "noise_cancellation": 5.0, "battery_life": 7.0, "value": 9.0},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="MidRange Max",
                    criterion_scores={"sound_quality": 7.0, "noise_cancellation": 6.5, "battery_life": 7.5, "value": 7.5},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="Baseline Buds",
                    criterion_scores={"sound_quality": 4.0, "noise_cancellation": 3.5, "battery_life": 5.0, "value": 8.0},
                    signal_strength="low",
                ),
            ],
            base_rubric=[
                RubricWeight("sound_quality",      "Sound Quality",      4.0),
                RubricWeight("noise_cancellation", "Noise Cancellation", 3.0),
                RubricWeight("battery_life",       "Battery Life",       2.0),
                RubricWeight("value",              "Value for Money",    1.0),
            ],
            min_spearman=0.85,
            tags=["earbuds", "clear_winner"],
        ),

        # ── sc-002: Tightly clustered — tolerate moderate instability ─────────
        StabilityScenario(
            id="sc-002",
            description="Laptops with near-identical scores — instability is expected",
            category="electronics/laptop",
            products=[
                ProductProfile(
                    name="LaptopA",
                    criterion_scores={"performance": 7.1, "display": 7.0, "battery": 7.2, "build": 7.0},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="LaptopB",
                    criterion_scores={"performance": 7.0, "display": 7.2, "battery": 7.0, "build": 7.1},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="LaptopC",
                    criterion_scores={"performance": 7.2, "display": 7.1, "battery": 6.9, "build": 7.0},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="LaptopD",
                    criterion_scores={"performance": 6.9, "display": 7.0, "battery": 7.1, "build": 7.2},
                    signal_strength="low",
                ),
            ],
            base_rubric=[
                RubricWeight("performance", "Performance", 3.0),
                RubricWeight("display",     "Display",     3.0),
                RubricWeight("battery",     "Battery",     2.0),
                RubricWeight("build",       "Build",       2.0),
            ],
            min_spearman=0.50,  # allow more variance — cluster is legitimately tight
            tags=["laptop", "tight_cluster"],
        ),

        # ── sc-003: Smartphones — two-tier separation ─────────────────────────
        StabilityScenario(
            id="sc-003",
            description="Smartphones with a clear top-2 vs bottom-3 split",
            category="electronics/smartphone",
            products=[
                ProductProfile(
                    name="FlexPhone Pro",
                    criterion_scores={"camera": 9.0, "performance": 8.5, "battery": 8.0, "value": 6.0},
                    signal_strength="high",
                ),
                ProductProfile(
                    name="PurePhone Ultra",
                    criterion_scores={"camera": 8.5, "performance": 9.0, "battery": 7.5, "value": 6.5},
                    signal_strength="high",
                ),
                ProductProfile(
                    name="MidPhone A",
                    criterion_scores={"camera": 6.5, "performance": 6.0, "battery": 7.0, "value": 8.0},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="MidPhone B",
                    criterion_scores={"camera": 5.5, "performance": 6.5, "battery": 7.5, "value": 8.5},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="BudgetPhone",
                    criterion_scores={"camera": 4.0, "performance": 4.5, "battery": 8.0, "value": 9.5},
                    signal_strength="low",
                ),
            ],
            base_rubric=[
                RubricWeight("camera",      "Camera",      4.0),
                RubricWeight("performance", "Performance", 3.0),
                RubricWeight("battery",     "Battery",     2.0),
                RubricWeight("value",       "Value",       1.0),
            ],
            min_spearman=0.75,
            tags=["smartphone", "two_tier"],
        ),

        # ── sc-004: Single criterion — trivially stable under weight changes ──
        StabilityScenario(
            id="sc-004",
            description="Single-criterion rubric — ranking is weight-agnostic",
            category="general/product",
            products=[
                ProductProfile(
                    name="Product Alpha",
                    criterion_scores={"quality": 9.0},
                    signal_strength="high",
                ),
                ProductProfile(
                    name="Product Beta",
                    criterion_scores={"quality": 7.0},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="Product Gamma",
                    criterion_scores={"quality": 5.0},
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="Product Delta",
                    criterion_scores={"quality": 3.0},
                    signal_strength="low",
                ),
            ],
            base_rubric=[
                RubricWeight("quality", "Quality", 10.0),
            ],
            min_spearman=1.0,  # single criterion → rank order never changes
            tags=["single_criterion"],
        ),

        # ── sc-005: Mattresses — 6 criteria, balanced weights ─────────────────
        StabilityScenario(
            id="sc-005",
            description="Mattresses with 6 criteria — moderate stability under perturbations",
            category="home/mattress",
            products=[
                ProductProfile(
                    name="DreamCloud Premier",
                    criterion_scores={
                        "comfort": 9.0, "support": 8.5, "edge_support": 7.0,
                        "motion_isolation": 8.0, "temperature": 7.5, "value": 6.0,
                    },
                    signal_strength="high",
                ),
                ProductProfile(
                    name="Saatva Classic",
                    criterion_scores={
                        "comfort": 8.0, "support": 9.0, "edge_support": 9.0,
                        "motion_isolation": 7.0, "temperature": 8.0, "value": 5.5,
                    },
                    signal_strength="high",
                ),
                ProductProfile(
                    name="Nectar Memory Foam",
                    criterion_scores={
                        "comfort": 7.5, "support": 7.0, "edge_support": 6.0,
                        "motion_isolation": 9.0, "temperature": 6.0, "value": 9.0,
                    },
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="Purple Hybrid",
                    criterion_scores={
                        "comfort": 7.0, "support": 7.5, "edge_support": 7.5,
                        "motion_isolation": 7.5, "temperature": 9.0, "value": 6.5,
                    },
                    signal_strength="moderate",
                ),
                ProductProfile(
                    name="Zinus Budget",
                    criterion_scores={
                        "comfort": 5.0, "support": 5.5, "edge_support": 4.0,
                        "motion_isolation": 6.0, "temperature": 5.5, "value": 9.5,
                    },
                    signal_strength="low",
                ),
            ],
            base_rubric=[
                RubricWeight("comfort",          "Comfort",           2.5),
                RubricWeight("support",          "Support",           2.5),
                RubricWeight("edge_support",     "Edge Support",      1.5),
                RubricWeight("motion_isolation", "Motion Isolation",  1.5),
                RubricWeight("temperature",      "Temperature",       1.0),
                RubricWeight("value",            "Value",             1.0),
            ],
            min_spearman=0.70,
            tags=["mattress", "many_criteria"],
        ),
    ]
