"""
End-to-end tests for Score Calibration Benchmark (Phase 12).

Coverage:
  - _extract_criterion_scores() from product dicts
  - check_score_spread() — detects compressed per-product criterion variance
  - check_grade_inflation() — detects excessive high-scoring (LLM leniency)
  - check_discrimination() — detects products clustering too close together
  - check_low_range_usage() — detects absence of weak scores
  - CalibrationSuite dataclass properties (passed, pass_rate, failures)
  - run_calibration_suite() — orchestrates all 4 checks
  - all_calibration_suites() — loads real recorded fixtures
  - ScoreCalibrationMetric.evaluate() — correct score, pass/fail, skipping
  - Config consistency: INDEX_WEIGHTS sum, score_calibration entries present
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from evals.benchmarks.score_calibration import (
    CalibrationCheck,
    CalibrationSuite,
    _extract_criterion_scores,
    check_score_spread,
    check_grade_inflation,
    check_discrimination,
    check_low_range_usage,
    run_calibration_suite,
    all_calibration_suites,
    MIN_SPREAD_PER_PRODUCT,
    HIGH_SCORE_THRESHOLD,
    HIGH_FRACTION_CEILING,
    MIN_DISCRIMINATION_PCT,
    LOW_SCORE_THRESHOLD,
    MIN_PRODUCTS,
)
from evals.metrics.score_calibration import ScoreCalibrationMetric


# ── Shared product fixtures ────────────────────────────────────────────────────

def _make_product(name: str, scores: list[float], percentage: float = 80.0) -> dict:
    """Build a recorded-fixture-shaped product dict."""
    return {
        "name": name,
        "percentage": percentage,
        "scores": [
            {"criterion": f"crit_{i}", "label": f"C{i}", "score": s}
            for i, s in enumerate(scores)
        ],
    }


def _make_good_products() -> list[dict]:
    """Three well-calibrated products — all 4 checks should pass."""
    return [
        _make_product("Alpha", [9.0, 8.0, 6.0, 7.0, 9.0], percentage=84.2),
        _make_product("Beta",  [9.0, 8.0, 6.0, 7.0, 8.0], percentage=81.0),
        _make_product("Gamma", [9.0, 7.0, 5.0, 6.0, 6.0], percentage=74.5),
    ]


def _make_inflated_products() -> list[dict]:
    """All scores 8-9 — grade_inflation check should fail."""
    return [
        _make_product("X", [9.0, 9.0, 8.0, 8.0, 9.0], percentage=90.0),
        _make_product("Y", [8.0, 9.0, 9.0, 8.0, 9.0], percentage=88.0),
        _make_product("Z", [9.0, 8.0, 9.0, 9.0, 8.0], percentage=86.0),
    ]


def _make_compressed_products() -> list[dict]:
    """All per-product spreads < 2.0 — score_spread check should fail."""
    return [
        _make_product("A", [7.5, 7.8, 7.2, 7.6, 7.4], percentage=82.0),
        _make_product("B", [6.8, 7.0, 6.9, 7.1, 6.8], percentage=78.0),
        _make_product("C", [5.9, 6.1, 5.8, 6.0, 6.2], percentage=70.0),
    ]


def _make_no_discrimination_products() -> list[dict]:
    """All products within 3 pp — discrimination check should fail."""
    return [
        _make_product("P", [8.0, 7.0, 6.0, 7.0, 7.0], percentage=80.0),
        _make_product("Q", [7.0, 8.0, 6.0, 7.0, 7.0], percentage=79.5),
        _make_product("R", [7.0, 7.0, 7.0, 7.0, 6.0], percentage=78.0),
    ]


def _make_no_low_scores_products() -> list[dict]:
    """All scores >= 6.0 — low_range_usage check should fail."""
    return [
        _make_product("M", [9.0, 8.0, 7.0, 6.5, 8.0], percentage=85.0),
        _make_product("N", [7.0, 6.0, 9.0, 8.0, 6.5], percentage=78.0),
        _make_product("O", [6.0, 7.0, 8.0, 6.5, 6.0], percentage=72.0),
    ]


# ── TestExtractCriterionScores ─────────────────────────────────────────────────

class TestExtractCriterionScores:

    def test_single_criterion_returns_float(self):
        p = {"scores": [{"criterion": "a", "score": 7}]}
        assert _extract_criterion_scores(p) == [7.0]

    def test_multiple_criteria_all_returned(self):
        p = {"scores": [
            {"criterion": "a", "score": 9},
            {"criterion": "b", "score": 6},
            {"criterion": "c", "score": 8},
        ]}
        assert _extract_criterion_scores(p) == [9.0, 6.0, 8.0]

    def test_empty_scores_list(self):
        assert _extract_criterion_scores({"scores": []}) == []

    def test_missing_scores_key(self):
        assert _extract_criterion_scores({"name": "X"}) == []

    def test_entry_without_score_key_skipped(self):
        p = {"scores": [{"criterion": "a"}, {"criterion": "b", "score": 5}]}
        assert _extract_criterion_scores(p) == [5.0]

    def test_float_scores_preserved(self):
        p = {"scores": [{"criterion": "a", "score": 8.3}]}
        assert _extract_criterion_scores(p) == [8.3]


# ── TestCheckScoreSpread ──────────────────────────────────────────────────────

class TestCheckScoreSpread:

    def test_passes_when_median_spread_meets_threshold(self):
        # spreads: 3, 3, 4 → median 3 ≥ 2.0
        result = check_score_spread(_make_good_products())
        assert result.passed is True
        assert result.name == "score_spread"

    def test_fails_when_median_spread_compressed(self):
        # spreads: 0.6, 0.3, 0.4 → median < 2.0
        result = check_score_spread(_make_compressed_products())
        assert result.passed is False

    def test_exact_threshold_passes(self):
        # spread == 2.0 exactly
        products = [_make_product("A", [8.0, 6.0], percentage=80.0)]
        result = check_score_spread(products)
        assert result.value == pytest.approx(2.0)
        assert result.passed is True

    def test_just_below_threshold_fails(self):
        products = [_make_product("A", [7.9, 6.0], percentage=80.0)]
        result = check_score_spread(products)
        assert result.value == pytest.approx(1.9)
        assert result.passed is False

    def test_single_criterion_per_product_skips(self):
        # Only 1 score per product → no spread computable
        products = [
            {"name": "A", "percentage": 80.0, "scores": [{"criterion": "a", "score": 8}]},
            {"name": "B", "percentage": 70.0, "scores": [{"criterion": "a", "score": 7}]},
        ]
        result = check_score_spread(products)
        assert result.passed is True
        assert "skipped" in result.description

    def test_empty_products_skips(self):
        result = check_score_spread([])
        assert result.passed is True
        assert "skipped" in result.description

    def test_threshold_is_correct(self):
        result = check_score_spread(_make_good_products())
        assert result.threshold == MIN_SPREAD_PER_PRODUCT

    def test_uses_median_not_mean(self):
        # Two products: spreads 10, 1 → median 5.5 ≥ 2.0 (passes)
        # Mean would be 5.5 too, but test with uneven data
        products = [
            _make_product("A", [10.0, 0.0], percentage=90.0),   # spread 10
            _make_product("B", [5.5, 4.5], percentage=80.0),     # spread 1.0
            _make_product("C", [7.0, 5.0], percentage=70.0),     # spread 2.0
        ]
        result = check_score_spread(products)
        # median([10, 1, 2]) = 2.0 → passes (exactly at threshold)
        assert result.value == pytest.approx(2.0)
        assert result.passed is True


# ── TestCheckGradeInflation ───────────────────────────────────────────────────

class TestCheckGradeInflation:

    def test_passes_when_high_fraction_below_ceiling(self):
        # good products: 7/15 = 46.7% ≥ 8.0 → passes (< 60%)
        result = check_grade_inflation(_make_good_products())
        assert result.passed is True
        assert result.name == "grade_inflation"

    def test_fails_when_high_fraction_above_ceiling(self):
        # inflated products: 14/15 ≈ 93% ≥ 8.0 → fails
        result = check_grade_inflation(_make_inflated_products())
        assert result.passed is False

    def test_exactly_at_ceiling_passes(self):
        # 3 scores: 2 high (8.0, 9.0), 1 low (5.0) → 2/3 = 66.7% > 60% → FAIL
        # 3 scores: all below 8 → 0/3 = 0% → PASS
        # Need exactly 60%: 3 high, 2 low = 60%
        products = [
            _make_product("A", [8.0, 8.0, 8.0, 5.0, 5.0], percentage=80.0),
        ]
        result = check_grade_inflation(products)
        assert result.value == pytest.approx(0.6, abs=0.001)
        assert result.passed is True   # ≤ 0.60

    def test_above_ceiling_fails(self):
        # 4 high, 1 low = 80% > 60%
        products = [_make_product("A", [9.0, 8.0, 9.0, 8.0, 4.0], percentage=80.0)]
        result = check_grade_inflation(products)
        assert result.passed is False

    def test_scores_equal_to_threshold_count_as_high(self):
        # score == 8.0 must count as "high"
        products = [_make_product("A", [8.0, 5.0], percentage=80.0)]
        result = check_grade_inflation(products)
        assert result.value == pytest.approx(0.5)   # 1/2 = 50%

    def test_all_low_scores_passes(self):
        products = [_make_product("A", [4.0, 5.0, 5.5, 3.0], percentage=70.0)]
        result = check_grade_inflation(products)
        assert result.passed is True
        assert result.value == pytest.approx(0.0)

    def test_no_scores_skips(self):
        products = [{"name": "A", "percentage": 80.0, "scores": []}]
        result = check_grade_inflation(products)
        assert result.passed is True
        assert "skipped" in result.description

    def test_empty_products_skips(self):
        result = check_grade_inflation([])
        assert result.passed is True
        assert "skipped" in result.description

    def test_threshold_is_correct(self):
        result = check_grade_inflation(_make_good_products())
        assert result.threshold == HIGH_FRACTION_CEILING


# ── TestCheckDiscrimination ───────────────────────────────────────────────────

class TestCheckDiscrimination:

    def test_passes_when_gap_large_enough(self):
        # 84.2 - 74.5 = 9.7 ≥ 5.0
        result = check_discrimination(_make_good_products())
        assert result.passed is True
        assert result.name == "discrimination"

    def test_fails_when_gap_too_small(self):
        # max 80 - min 78 = 2 < 5.0
        result = check_discrimination(_make_no_discrimination_products())
        assert result.passed is False

    def test_exact_threshold_passes(self):
        products = [
            _make_product("A", [8.0, 7.0], percentage=80.0),
            _make_product("B", [6.0, 5.0], percentage=75.0),
        ]
        result = check_discrimination(products)
        assert result.value == pytest.approx(5.0)
        assert result.passed is True   # >= 5.0

    def test_one_below_threshold_fails(self):
        products = [
            _make_product("A", [8.0], percentage=79.9),
            _make_product("B", [6.0], percentage=75.0),
        ]
        result = check_discrimination(products)
        assert result.value == pytest.approx(4.9)
        assert result.passed is False

    def test_single_product_skips(self):
        products = [_make_product("Solo", [8.0, 7.0], percentage=80.0)]
        result = check_discrimination(products)
        assert result.passed is True
        assert "skipped" in result.description

    def test_empty_products_skips(self):
        result = check_discrimination([])
        assert result.passed is True

    def test_reads_percentage_field(self):
        products = [
            {"name": "A", "percentage": 90.0, "scores": []},
            {"name": "B", "percentage": 60.0, "scores": []},
        ]
        result = check_discrimination(products)
        assert result.value == pytest.approx(30.0)
        assert result.passed is True

    def test_threshold_is_correct(self):
        result = check_discrimination(_make_good_products())
        assert result.threshold == MIN_DISCRIMINATION_PCT


# ── TestCheckLowRangeUsage ────────────────────────────────────────────────────

class TestCheckLowRangeUsage:

    def test_passes_when_low_score_exists(self):
        # good products have fit_security=5 → passes
        result = check_low_range_usage(_make_good_products())
        assert result.passed is True
        assert result.name == "low_range_usage"

    def test_fails_when_all_scores_above_threshold(self):
        result = check_low_range_usage(_make_no_low_scores_products())
        assert result.passed is False

    def test_exact_threshold_passes(self):
        products = [_make_product("A", [5.5, 8.0, 9.0], percentage=80.0)]
        result = check_low_range_usage(products)
        assert result.value == pytest.approx(5.5)
        assert result.passed is True   # <= 5.5

    def test_above_threshold_fails(self):
        products = [_make_product("A", [5.6, 8.0, 9.0], percentage=80.0)]
        result = check_low_range_usage(products)
        assert result.value == pytest.approx(5.6)
        assert result.passed is False

    def test_zero_score_passes(self):
        products = [_make_product("A", [0.0, 9.0], percentage=80.0)]
        result = check_low_range_usage(products)
        assert result.passed is True

    def test_no_scores_skips(self):
        products = [{"name": "A", "percentage": 80.0, "scores": []}]
        result = check_low_range_usage(products)
        assert result.passed is True
        assert "skipped" in result.description

    def test_low_score_in_one_product_is_enough(self):
        # Only the last product has a low score
        products = [
            _make_product("A", [8.0, 9.0, 7.0], percentage=85.0),
            _make_product("B", [9.0, 8.0, 7.0], percentage=80.0),
            _make_product("C", [5.0, 8.0, 9.0], percentage=70.0),   # score 5.0 <= 5.5
        ]
        result = check_low_range_usage(products)
        assert result.passed is True

    def test_threshold_is_correct(self):
        result = check_low_range_usage(_make_good_products())
        assert result.threshold == LOW_SCORE_THRESHOLD


# ── TestCalibrationSuiteProperties ───────────────────────────────────────────

class TestCalibrationSuiteProperties:

    def _pass_check(self, name="test") -> CalibrationCheck:
        return CalibrationCheck(name, True, 0.5, 0.6, f"{name}: pass")

    def _fail_check(self, name="test") -> CalibrationCheck:
        return CalibrationCheck(name, False, 0.8, 0.6, f"{name}: fail")

    def test_suite_passed_when_all_checks_pass(self):
        suite = CalibrationSuite(
            suite_id="x", product_count=3, criterion_count=15,
            checks=[self._pass_check("a"), self._pass_check("b")],
        )
        assert suite.passed is True

    def test_suite_failed_when_any_check_fails(self):
        suite = CalibrationSuite(
            suite_id="x", product_count=3, criterion_count=15,
            checks=[self._pass_check("a"), self._fail_check("b")],
        )
        assert suite.passed is False

    def test_pass_rate_all_passing(self):
        suite = CalibrationSuite(
            suite_id="x", product_count=3, criterion_count=15,
            checks=[self._pass_check(), self._pass_check(), self._pass_check()],
        )
        assert suite.pass_rate == pytest.approx(1.0)

    def test_pass_rate_partial(self):
        suite = CalibrationSuite(
            suite_id="x", product_count=3, criterion_count=15,
            checks=[self._pass_check(), self._fail_check(), self._pass_check()],
        )
        assert suite.pass_rate == pytest.approx(2 / 3)

    def test_skipped_suite_always_passed(self):
        suite = CalibrationSuite(
            suite_id="x", product_count=1, criterion_count=0,
            skipped=True, skip_reason="not enough products",
        )
        assert suite.passed is True
        assert suite.pass_rate == pytest.approx(1.0)

    def test_failures_list_only_failed_checks(self):
        suite = CalibrationSuite(
            suite_id="x", product_count=3, criterion_count=15,
            checks=[self._pass_check("good"), self._fail_check("bad")],
        )
        assert len(suite.failures) == 1
        assert "bad" in suite.failures[0]

    def test_empty_checks_pass_rate_is_one(self):
        suite = CalibrationSuite(suite_id="x", product_count=2, criterion_count=10)
        assert suite.pass_rate == pytest.approx(1.0)


# ── TestRunCalibrationSuite ───────────────────────────────────────────────────

class TestRunCalibrationSuite:

    def test_good_products_all_checks_pass(self):
        suite = run_calibration_suite("good", _make_good_products())
        assert not suite.skipped
        assert suite.passed is True
        assert len(suite.checks) == 4

    def test_always_has_four_checks_for_active_suite(self):
        suite = run_calibration_suite("x", _make_good_products())
        assert len(suite.checks) == 4

    def test_single_product_skips(self):
        products = [_make_product("Solo", [8.0, 7.0, 6.0], percentage=80.0)]
        suite = run_calibration_suite("single", products)
        assert suite.skipped is True
        assert suite.passed is True

    def test_zero_products_skips(self):
        suite = run_calibration_suite("empty", [])
        assert suite.skipped is True

    def test_inflated_products_fail_grade_inflation(self):
        suite = run_calibration_suite("inflated", _make_inflated_products())
        assert not suite.skipped
        inflated_check = next(c for c in suite.checks if c.name == "grade_inflation")
        assert inflated_check.passed is False

    def test_no_discrimination_fails_discrimination_check(self):
        suite = run_calibration_suite("nodiscrim", _make_no_discrimination_products())
        discrim_check = next(c for c in suite.checks if c.name == "discrimination")
        assert discrim_check.passed is False

    def test_product_count_recorded(self):
        suite = run_calibration_suite("x", _make_good_products())
        assert suite.product_count == 3

    def test_criterion_count_recorded(self):
        # 3 products × 5 criteria = 15
        suite = run_calibration_suite("x", _make_good_products())
        assert suite.criterion_count == 15

    def test_suite_id_stored(self):
        suite = run_calibration_suite("my_fixture", _make_good_products())
        assert suite.suite_id == "my_fixture"


# ── TestAllCalibrationSuites ──────────────────────────────────────────────────

class TestAllCalibrationSuites:

    def test_returns_non_empty_list(self):
        suites = all_calibration_suites()
        assert len(suites) >= 1

    def test_earbuds_fixture_present(self):
        suites = all_calibration_suites()
        ids = [s.suite_id for s in suites]
        # The earbuds query becomes the suite_id
        assert any("earbuds" in sid or "gym" in sid or "wireless" in sid for sid in ids)

    def test_all_suites_have_suite_id(self):
        for suite in all_calibration_suites():
            assert suite.suite_id != ""

    def test_real_fixture_passes_all_checks(self):
        suites = all_calibration_suites()
        active = [s for s in suites if not s.skipped]
        assert len(active) >= 1
        # All 4 checks on the earbuds fixture must pass
        for suite in active:
            assert suite.passed, (
                f"Suite '{suite.suite_id}' failed: {suite.failures}"
            )

    def test_real_fixture_pass_rate_is_100(self):
        suites = all_calibration_suites()
        active = [s for s in suites if not s.skipped]
        for suite in active:
            assert suite.pass_rate == pytest.approx(1.0), (
                f"Suite '{suite.suite_id}' pass_rate {suite.pass_rate:.2%}: {suite.failures}"
            )


# ── TestScoreCalibrationMetric ────────────────────────────────────────────────

class TestScoreCalibrationMetric:

    def _pass_suite(self, sid="good") -> CalibrationSuite:
        return run_calibration_suite(sid, _make_good_products())

    def _fail_suite(self, sid="bad") -> CalibrationSuite:
        """Suite where grade_inflation and low_range checks fail."""
        return run_calibration_suite(sid, _make_inflated_products())

    def _skip_suite(self, sid="skip") -> CalibrationSuite:
        return run_calibration_suite(sid, [_make_product("Solo", [8.0, 7.0])])

    def test_metric_name(self):
        assert ScoreCalibrationMetric.name == "score_calibration"

    def test_skips_when_no_suites(self):
        result = ScoreCalibrationMetric().evaluate([])
        assert result.skipped is True
        assert result.passed is True

    def test_skips_when_all_suites_skipped(self):
        result = ScoreCalibrationMetric().evaluate([self._skip_suite()])
        assert result.skipped is True
        assert result.passed is True

    def test_100_score_on_all_passing_suites(self):
        result = ScoreCalibrationMetric().evaluate([self._pass_suite()])
        assert result.score == pytest.approx(100.0)

    def test_passes_when_score_above_threshold(self):
        result = ScoreCalibrationMetric().evaluate([self._pass_suite()])
        assert result.passed is True

    def test_score_reflects_failing_checks(self):
        # inflated suite: 2 checks fail (grade_inflation, low_range_usage)
        # → 2/4 pass = 50%
        suite = self._fail_suite()
        failed_count = sum(1 for c in suite.checks if not c.passed)
        passed_count = sum(1 for c in suite.checks if c.passed)
        expected_score = passed_count / 4 * 100
        result = ScoreCalibrationMetric().evaluate([suite])
        assert result.score == pytest.approx(expected_score, abs=0.1)

    def test_failures_list_populated_for_failed_checks(self):
        result = ScoreCalibrationMetric().evaluate([self._fail_suite("bad_fixture")])
        assert len(result.failures) > 0
        assert any("bad_fixture" in f for f in result.failures)

    def test_details_has_required_keys(self):
        result = ScoreCalibrationMetric().evaluate([self._pass_suite()])
        for key in ("total_suites", "active_suites", "skipped_suites",
                    "total_checks", "passed_checks", "suites"):
            assert key in result.details, f"Missing key '{key}' in details"

    def test_skipped_suites_counted_in_details(self):
        suites = [self._pass_suite(), self._skip_suite()]
        result = ScoreCalibrationMetric().evaluate(suites)
        assert result.details["total_suites"] == 2
        assert result.details["skipped_suites"] == 1
        assert result.details["active_suites"] == 1

    def test_real_data_returns_100(self):
        """Integration: metric on actual earbuds fixture must score 100."""
        suites = all_calibration_suites()
        result = ScoreCalibrationMetric().evaluate(suites)
        assert not result.skipped
        assert result.score == pytest.approx(100.0), (
            f"Expected 100.0 on clean fixture, got {result.score}: {result.failures}"
        )

    def test_real_data_passes(self):
        suites = all_calibration_suites()
        result = ScoreCalibrationMetric().evaluate(suites)
        assert result.passed, f"score_calibration failed on real data: {result.failures}"

    def test_multi_suite_score_averages_checks(self):
        """Two suites: one all-pass (4/4), one partially-fail (2/4) → (4+2)/8 = 75%."""
        suite_good = self._pass_suite("suite_good")
        suite_bad = self._fail_suite("suite_bad")
        passed_good = sum(1 for c in suite_good.checks if c.passed)
        passed_bad = sum(1 for c in suite_bad.checks if c.passed)
        expected = (passed_good + passed_bad) / 8 * 100
        result = ScoreCalibrationMetric().evaluate([suite_good, suite_bad])
        assert result.score == pytest.approx(expected, abs=0.1)


# ── TestConfigConsistency ─────────────────────────────────────────────────────

class TestConfigConsistency:

    def test_score_calibration_in_index_weights(self):
        from evals.config import INDEX_WEIGHTS
        assert "score_calibration" in INDEX_WEIGHTS

    def test_index_weights_sum_to_one(self):
        from evals.config import INDEX_WEIGHTS
        total = sum(INDEX_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, (
            f"INDEX_WEIGHTS sum {total:.10f} ≠ 1.0"
        )

    def test_score_calibration_pass_threshold_set(self):
        from evals.config import PASS_THRESHOLDS
        assert "score_calibration" in PASS_THRESHOLDS
        assert PASS_THRESHOLDS["score_calibration"] > 0

    def test_score_calibration_ci_block_set(self):
        from evals.config import CI_BLOCK_THRESHOLDS
        assert "score_calibration" in CI_BLOCK_THRESHOLDS
        assert CI_BLOCK_THRESHOLDS["score_calibration"] > 0

    def test_score_calibration_in_quick_eval_metrics(self):
        from evals.config import QUICK_EVAL_METRICS
        assert "score_calibration" in QUICK_EVAL_METRICS

    def test_ci_block_below_pass_threshold(self):
        from evals.config import PASS_THRESHOLDS, CI_BLOCK_THRESHOLDS
        pt = PASS_THRESHOLDS["score_calibration"]
        ci = CI_BLOCK_THRESHOLDS["score_calibration"]
        assert ci < pt, (
            f"CI block {ci} should be below pass threshold {pt}"
        )

    def test_all_quick_metrics_have_index_weight(self):
        from evals.config import QUICK_EVAL_METRICS, INDEX_WEIGHTS
        for m in QUICK_EVAL_METRICS:
            assert m in INDEX_WEIGHTS, f"Quick metric '{m}' missing from INDEX_WEIGHTS"
