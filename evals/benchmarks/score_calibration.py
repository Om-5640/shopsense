"""
Score Calibration benchmark.

Detects grade-inflation (LLM leniency bias) in recorded pipeline-output fixtures.
Grade inflation = LLM systematically scores all products 8-9/10, removing the
meaningful quality signal that makes rankings trustworthy.

Four checks per fixture:
  1. score_spread     — median per-product (max−min) criterion spread ≥ 2.0
                        Compressed spreads mean the LLM treats all criteria similarly.
  2. grade_inflation  — ≤ 60% of criterion scores are ≥ 8.0
                        Excessive high-scoring = LLM leniency (positive confirmation bias).
  3. discrimination   — top vs bottom product percentage-point gap ≥ 5.0 pp
                        If products cluster together, rankings are dominated by noise.
  4. low_range_usage  — at least one criterion score ≤ 5.5
                        A calibrated scorer must assign weak scores, not just varying 7-9.

Score = (passing_checks / total_checks) × 100 across all recorded fixtures.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from evals.benchmarks.recorded import load_recorded_fixtures

# ── Calibration thresholds ────────────────────────────────────────────────────
MIN_SPREAD_PER_PRODUCT: float = 2.0   # median(max_criterion − min_criterion) per product
HIGH_SCORE_THRESHOLD: float = 8.0     # criterion scores ≥ this count as "high"
HIGH_FRACTION_CEILING: float = 0.60   # at most 60% of scores may be high
MIN_DISCRIMINATION_PCT: float = 5.0   # pp gap between top and bottom product
LOW_SCORE_THRESHOLD: float = 5.5      # at least one criterion must be ≤ this

MIN_PRODUCTS: int = 2    # need ≥ 2 products to run checks
MIN_CRITERIA: int = 2    # need ≥ 2 criteria per product to compute spread


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class CalibrationCheck:
    name: str
    passed: bool
    value: float       # measured value
    threshold: float   # threshold it was compared against
    description: str   # human-readable outcome


@dataclass
class CalibrationSuite:
    suite_id: str
    product_count: int
    criterion_count: int   # total criterion scores across all products
    checks: list[CalibrationCheck] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    @property
    def passed(self) -> bool:
        if self.skipped:
            return True
        return all(c.passed for c in self.checks)

    @property
    def pass_rate(self) -> float:
        if self.skipped or not self.checks:
            return 1.0
        return sum(1 for c in self.checks if c.passed) / len(self.checks)

    @property
    def failures(self) -> list[str]:
        return [c.description for c in self.checks if not c.passed]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_criterion_scores(product: dict) -> list[float]:
    """Return a flat list of criterion score values (0-10) from a recorded-fixture product."""
    return [
        float(entry["score"])
        for entry in product.get("scores", [])
        if "score" in entry
    ]


# ── Individual check functions ────────────────────────────────────────────────

def check_score_spread(products: list[dict]) -> CalibrationCheck:
    """
    Per-product internal spread: median(max_criterion − min_criterion) ≥ MIN_SPREAD_PER_PRODUCT.
    A well-calibrated LLM assigns clearly differentiated scores across criteria for each product.
    """
    spreads: list[float] = []
    for p in products:
        scores = _extract_criterion_scores(p)
        if len(scores) >= MIN_CRITERIA:
            spreads.append(max(scores) - min(scores))

    if not spreads:
        return CalibrationCheck(
            "score_spread", True, 0.0, MIN_SPREAD_PER_PRODUCT,
            "score_spread: insufficient criteria data (skipped)",
        )

    median_spread = statistics.median(spreads)
    passed = median_spread >= MIN_SPREAD_PER_PRODUCT
    label = "acceptable internal variance" if passed else "criteria scores compressed (possible inflation)"
    return CalibrationCheck(
        "score_spread", passed,
        round(median_spread, 2), MIN_SPREAD_PER_PRODUCT,
        (
            f"score_spread: median per-product spread {median_spread:.2f} "
            f"({'≥' if passed else '<'} {MIN_SPREAD_PER_PRODUCT}) — {label}"
        ),
    )


def check_grade_inflation(products: list[dict]) -> CalibrationCheck:
    """
    ≤ HIGH_FRACTION_CEILING of all criterion scores may be ≥ HIGH_SCORE_THRESHOLD.
    If 60%+ of all scores are 8+ the LLM is exhibiting leniency bias.
    """
    all_scores = [s for p in products for s in _extract_criterion_scores(p)]
    if not all_scores:
        return CalibrationCheck(
            "grade_inflation", True, 0.0, HIGH_FRACTION_CEILING,
            "grade_inflation: no scores found (skipped)",
        )

    high_fraction = sum(1 for s in all_scores if s >= HIGH_SCORE_THRESHOLD) / len(all_scores)
    passed = high_fraction <= HIGH_FRACTION_CEILING
    label = "acceptable" if passed else "excessive high-scoring — LLM leniency detected"
    return CalibrationCheck(
        "grade_inflation", passed,
        round(high_fraction, 3), HIGH_FRACTION_CEILING,
        (
            f"grade_inflation: {high_fraction:.1%} of scores ≥ {HIGH_SCORE_THRESHOLD:.0f} "
            f"({label})"
        ),
    )


def check_discrimination(products: list[dict]) -> CalibrationCheck:
    """
    Top-vs-bottom product percentage-point gap ≥ MIN_DISCRIMINATION_PCT.
    If products cluster within 5 pp the ranking is dominated by noise, not signal.
    """
    percentages = [float(p.get("percentage", 0.0)) for p in products]
    if len(percentages) < MIN_PRODUCTS:
        return CalibrationCheck(
            "discrimination", True, 0.0, MIN_DISCRIMINATION_PCT,
            "discrimination: fewer than 2 products (skipped)",
        )

    pct_range = max(percentages) - min(percentages)
    passed = pct_range >= MIN_DISCRIMINATION_PCT
    label = "meaningful differentiation" if passed else "products indistinguishable — noise-driven ranking"
    return CalibrationCheck(
        "discrimination", passed,
        round(pct_range, 2), MIN_DISCRIMINATION_PCT,
        f"discrimination: {pct_range:.1f} pp gap ({label})",
    )


def check_low_range_usage(products: list[dict]) -> CalibrationCheck:
    """
    At least one criterion score must be ≤ LOW_SCORE_THRESHOLD.
    An LLM that never assigns low scores cannot distinguish strong from weak criteria.
    """
    all_scores = [s for p in products for s in _extract_criterion_scores(p)]
    if not all_scores:
        return CalibrationCheck(
            "low_range_usage", True, float("inf"), LOW_SCORE_THRESHOLD,
            "low_range_usage: no scores found (skipped)",
        )

    min_score = min(all_scores)
    any_low = min_score <= LOW_SCORE_THRESHOLD
    label = "low end used" if any_low else f"no score ≤ {LOW_SCORE_THRESHOLD} — high-end compression"
    return CalibrationCheck(
        "low_range_usage", any_low,
        round(min_score, 2), LOW_SCORE_THRESHOLD,
        f"low_range_usage: min score {min_score:.1f} ({label})",
    )


# ── Suite runner ──────────────────────────────────────────────────────────────

def run_calibration_suite(suite_id: str, products: list[dict]) -> CalibrationSuite:
    """Run all four calibration checks against one recorded fixture's product list."""
    if len(products) < MIN_PRODUCTS:
        return CalibrationSuite(
            suite_id=suite_id,
            product_count=len(products),
            criterion_count=0,
            skipped=True,
            skip_reason=f"only {len(products)} product(s) — need ≥ {MIN_PRODUCTS}",
        )

    total_criteria = sum(len(_extract_criterion_scores(p)) for p in products)

    checks = [
        check_score_spread(products),
        check_grade_inflation(products),
        check_discrimination(products),
        check_low_range_usage(products),
    ]

    return CalibrationSuite(
        suite_id=suite_id,
        product_count=len(products),
        criterion_count=total_criteria,
        checks=checks,
    )


def all_calibration_suites() -> list[CalibrationSuite]:
    """Load all recorded fixtures and return one CalibrationSuite per fixture."""
    suites: list[CalibrationSuite] = []
    for fixture in load_recorded_fixtures():
        meta = fixture.get("_meta", {})
        raw_id = meta.get("query", "unknown_fixture")
        suite_id = raw_id.replace(" ", "_")[:50]
        products = fixture.get("scored_products", [])
        suites.append(run_calibration_suite(suite_id, products))
    return suites
