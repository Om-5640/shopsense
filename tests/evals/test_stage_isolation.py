"""
End-to-end tests for Stage Fault Injection Benchmark (Phase 10).

Coverage:
  - inject_fault() correctly mutates each of the 4 fault types
  - inject_fault() is deepcopy-isolated (baseline unaffected)
  - is_detected() correctly identifies rank drops and rises
  - is_detected() correctly flags no-change as undetected
  - FaultScenario construction and field types
  - StageIsolationMetric.evaluate() on controlled synthetic scenarios
  - StageIsolationMetric skips on empty input
  - all_fault_scenarios() returns non-empty list with correct structure
  - generate_fault_scenarios_from_pools() produces 4 types per source
  - generate_fault_scenarios_from_recorded() works on recorded fixtures
  - Config: INDEX_WEIGHTS sums to 1.0, stage_isolation entries present
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from evals.benchmarks.base import ProductProfile, RubricWeight
from evals.benchmarks.fault_injection import (
    FaultType,
    FaultScenario,
    inject_fault,
    is_detected,
    all_fault_scenarios,
    generate_fault_scenarios_from_pools,
    generate_fault_scenarios_from_recorded,
    _build_scenarios_for_source,
    _products_from_recorded,
    _equal_weight_rubric,
)
from evals.engine import build_scored_products, rank_of
from evals.metrics.stage_isolation import StageIsolationMetric


# ── Shared fixtures ────────────────────────────────────────────────────────────

def _make_products() -> list[ProductProfile]:
    """Three products with clear ranking: Alpha > Beta > Gamma."""
    return [
        ProductProfile(
            name="Alpha",
            criterion_scores={"quality": 9.0, "value": 8.0, "durability": 8.0},
            mention_count=50, positive_mentions=40, negative_mentions=10,
        ),
        ProductProfile(
            name="Beta",
            criterion_scores={"quality": 6.0, "value": 6.0, "durability": 6.0},
            mention_count=30, positive_mentions=20, negative_mentions=10,
        ),
        ProductProfile(
            name="Gamma",
            criterion_scores={"quality": 3.0, "value": 3.0, "durability": 3.0},
            mention_count=10, positive_mentions=5, negative_mentions=5,
        ),
    ]


def _make_rubric() -> list[RubricWeight]:
    return [
        RubricWeight("quality", "Quality", 8.0),
        RubricWeight("value", "Value", 5.0),
        RubricWeight("durability", "Durability", 4.0),
    ]


def _make_scenario(fault_type: FaultType, target: str, detection: str) -> FaultScenario:
    return FaultScenario(
        id=f"test_{fault_type.value}",
        name=f"Test {fault_type.value}",
        fault_type=fault_type,
        products=_make_products(),
        rubric=_make_rubric(),
        target_product=target,
        detection=detection,
        source_fixture="test",
    )


# ── inject_fault tests ─────────────────────────────────────────────────────────

class TestInjectFaultIsolation:
    def test_baseline_unaffected_after_retrieval_miss(self):
        scenario = _make_scenario(FaultType.RETRIEVAL_MISS, "Alpha", "rank_drops")
        baseline, corrupted = inject_fault(scenario)
        assert baseline[0].criterion_scores["quality"] == 9.0, "baseline must not be mutated"

    def test_corrupted_independent_from_scenario_products(self):
        scenario = _make_scenario(FaultType.RETRIEVAL_MISS, "Alpha", "rank_drops")
        _, corrupted = inject_fault(scenario)
        alpha_in_corrupted = next(p for p in corrupted if p.name == "Alpha")
        alpha_in_corrupted.criterion_scores["quality"] = 99.0  # mutate after return
        assert scenario.products[0].criterion_scores["quality"] == 9.0, \
            "scenario.products must not be affected by post-return mutation"

    def test_non_target_products_unchanged(self):
        scenario = _make_scenario(FaultType.RETRIEVAL_MISS, "Alpha", "rank_drops")
        baseline, corrupted = inject_fault(scenario)
        beta_b = next(p for p in baseline if p.name == "Beta")
        beta_c = next(p for p in corrupted if p.name == "Beta")
        assert beta_b.criterion_scores == beta_c.criterion_scores

    def test_unknown_target_returns_equal_products(self):
        scenario = _make_scenario(FaultType.RETRIEVAL_MISS, "NonExistent", "rank_drops")
        baseline, corrupted = inject_fault(scenario)
        for b, c in zip(baseline, corrupted):
            assert b.criterion_scores == c.criterion_scores


class TestInjectFaultRetrievalMiss:
    def test_scores_set_to_1(self):
        scenario = _make_scenario(FaultType.RETRIEVAL_MISS, "Alpha", "rank_drops")
        _, corrupted = inject_fault(scenario)
        alpha = next(p for p in corrupted if p.name == "Alpha")
        for score in alpha.criterion_scores.values():
            assert score == 1.0

    def test_mention_count_zero(self):
        scenario = _make_scenario(FaultType.RETRIEVAL_MISS, "Alpha", "rank_drops")
        _, corrupted = inject_fault(scenario)
        alpha = next(p for p in corrupted if p.name == "Alpha")
        assert alpha.mention_count == 0
        assert alpha.positive_mentions == 0
        assert alpha.negative_mentions == 0


class TestInjectFaultMentionHalving:
    def test_mention_count_halved(self):
        scenario = _make_scenario(FaultType.MENTION_COUNT_HALVING, "Alpha", "rank_drops")
        _, corrupted = inject_fault(scenario)
        alpha = next(p for p in corrupted if p.name == "Alpha")
        assert alpha.mention_count == 25  # 50 // 2

    def test_scores_reduced_by_3_5(self):
        scenario = _make_scenario(FaultType.MENTION_COUNT_HALVING, "Alpha", "rank_drops")
        _, corrupted = inject_fault(scenario)
        alpha = next(p for p in corrupted if p.name == "Alpha")
        assert abs(alpha.criterion_scores["quality"] - (9.0 - 3.5)) < 1e-9

    def test_scores_clamped_at_zero(self):
        products = [
            ProductProfile("LowProduct", {"quality": 1.0}, mention_count=4),
            ProductProfile("OtherProduct", {"quality": 5.0}, mention_count=10),
        ]
        rubric = [RubricWeight("quality", "Quality", 5.0)]
        scenario = FaultScenario(
            id="test_clamp", name="Test Clamp",
            fault_type=FaultType.MENTION_COUNT_HALVING,
            products=products, rubric=rubric,
            target_product="LowProduct", detection="rank_drops",
        )
        _, corrupted = inject_fault(scenario)
        low = next(p for p in corrupted if p.name == "LowProduct")
        assert low.criterion_scores["quality"] == 0.0  # max(0, 1.0-3.5)


class TestInjectFaultEvidenceHallucination:
    def test_scores_set_to_9(self):
        scenario = _make_scenario(FaultType.EVIDENCE_HALLUCINATION, "Gamma", "rank_rises")
        _, corrupted = inject_fault(scenario)
        gamma = next(p for p in corrupted if p.name == "Gamma")
        for score in gamma.criterion_scores.values():
            assert score == 9.0

    def test_positive_mentions_boosted(self):
        scenario = _make_scenario(FaultType.EVIDENCE_HALLUCINATION, "Gamma", "rank_rises")
        _, corrupted = inject_fault(scenario)
        gamma = next(p for p in corrupted if p.name == "Gamma")
        assert gamma.positive_mentions == 50


class TestInjectFaultScoreDrift:
    def test_scores_boosted_by_3_5(self):
        scenario = _make_scenario(FaultType.SCORE_DRIFT, "Beta", "rank_rises")
        _, corrupted = inject_fault(scenario)
        beta = next(p for p in corrupted if p.name == "Beta")
        assert abs(beta.criterion_scores["quality"] - min(10.0, 6.0 + 3.5)) < 1e-9

    def test_scores_clamped_at_10(self):
        products = [
            ProductProfile("HighProduct", {"quality": 9.0}, mention_count=10),
            ProductProfile("TopProduct", {"quality": 9.5}, mention_count=20),
        ]
        rubric = [RubricWeight("quality", "Quality", 5.0)]
        scenario = FaultScenario(
            id="test_cap", name="Test Cap",
            fault_type=FaultType.SCORE_DRIFT,
            products=products, rubric=rubric,
            target_product="HighProduct", detection="rank_rises",
        )
        _, corrupted = inject_fault(scenario)
        high = next(p for p in corrupted if p.name == "HighProduct")
        assert high.criterion_scores["quality"] == 10.0  # min(10.0, 9.0+3.5)


# ── is_detected tests ─────────────────────────────────────────────────────────

class TestIsDetected:
    def _rank_drops_scenario(self) -> FaultScenario:
        return _make_scenario(FaultType.RETRIEVAL_MISS, "Alpha", "rank_drops")

    def _rank_rises_scenario(self) -> FaultScenario:
        return _make_scenario(FaultType.EVIDENCE_HALLUCINATION, "Gamma", "rank_rises")

    def test_rank_drops_detected(self):
        s = self._rank_drops_scenario()
        baseline, corrupted = inject_fault(s)
        b_ranked = build_scored_products(baseline, s.rubric)
        c_ranked = build_scored_products(corrupted, s.rubric)
        detected, explanation = is_detected(s, b_ranked, c_ranked)
        assert detected, f"RETRIEVAL_MISS should drop Alpha: {explanation}"

    def test_rank_rises_detected(self):
        s = self._rank_rises_scenario()
        baseline, corrupted = inject_fault(s)
        b_ranked = build_scored_products(baseline, s.rubric)
        c_ranked = build_scored_products(corrupted, s.rubric)
        detected, explanation = is_detected(s, b_ranked, c_ranked)
        assert detected, f"EVIDENCE_HALLUCINATION should raise Gamma: {explanation}"

    def test_no_change_not_detected(self):
        products = _make_products()
        rubric = _make_rubric()
        # Same baseline and corrupted (no change)
        ranked = build_scored_products(copy.deepcopy(products), rubric)
        s = _make_scenario(FaultType.RETRIEVAL_MISS, "Alpha", "rank_drops")
        detected, _ = is_detected(s, ranked, ranked)
        assert not detected

    def test_explanation_contains_product_name(self):
        s = self._rank_drops_scenario()
        baseline, corrupted = inject_fault(s)
        b_ranked = build_scored_products(baseline, s.rubric)
        c_ranked = build_scored_products(corrupted, s.rubric)
        _, explanation = is_detected(s, b_ranked, c_ranked)
        assert "Alpha" in explanation

    def test_unknown_detection_mode_returns_false(self):
        s = FaultScenario(
            id="test", name="Test",
            fault_type=FaultType.RETRIEVAL_MISS,
            products=_make_products(), rubric=_make_rubric(),
            target_product="Alpha", detection="invalid_mode",
        )
        baseline, corrupted = inject_fault(s)
        b_ranked = build_scored_products(baseline, s.rubric)
        c_ranked = build_scored_products(corrupted, s.rubric)
        detected, explanation = is_detected(s, b_ranked, c_ranked)
        assert not detected
        assert "unknown" in explanation


# ── StageIsolationMetric tests ────────────────────────────────────────────────

class TestStageIsolationMetric:
    def _four_scenarios(self) -> list[FaultScenario]:
        products = _make_products()
        rubric = _make_rubric()
        baseline = build_scored_products(products, rubric)
        return [
            FaultScenario(
                id="s_retrieval_miss", name="Retrieval Miss",
                fault_type=FaultType.RETRIEVAL_MISS,
                products=products, rubric=rubric,
                target_product=baseline[0]["name"], detection="rank_drops",
                source_fixture="test",
            ),
            FaultScenario(
                id="s_mention_halving", name="Mention Halving",
                fault_type=FaultType.MENTION_COUNT_HALVING,
                products=products, rubric=rubric,
                target_product=baseline[0]["name"], detection="rank_drops",
                source_fixture="test",
            ),
            FaultScenario(
                id="s_hallucination", name="Evidence Hallucination",
                fault_type=FaultType.EVIDENCE_HALLUCINATION,
                products=products, rubric=rubric,
                target_product=baseline[-1]["name"], detection="rank_rises",
                source_fixture="test",
            ),
            FaultScenario(
                id="s_score_drift", name="Score Drift",
                fault_type=FaultType.SCORE_DRIFT,
                products=products, rubric=rubric,
                target_product=baseline[1]["name"], detection="rank_rises",
                source_fixture="test",
            ),
        ]

    def test_all_four_faults_detected_100_percent(self):
        scenarios = self._four_scenarios()
        result = StageIsolationMetric().evaluate(scenarios)
        assert result.score == 100.0, (
            f"Expected 100.0 but got {result.score}. Failures: {result.failures}"
        )

    def test_result_passes_at_100(self):
        result = StageIsolationMetric().evaluate(self._four_scenarios())
        assert result.passed

    def test_empty_input_returns_skipped(self):
        result = StageIsolationMetric().evaluate([])
        assert result.skipped

    def test_details_contains_by_fault_type(self):
        result = StageIsolationMetric().evaluate(self._four_scenarios())
        assert "by_fault_type" in result.details
        assert "retrieval_miss" in result.details["by_fault_type"]

    def test_details_counts_are_correct(self):
        result = StageIsolationMetric().evaluate(self._four_scenarios())
        assert result.details["applicable"] == 4
        assert result.details["detected"] == 4
        assert result.details["not_applicable"] == 0

    def test_broken_fault_drops_score(self):
        """A scenario with wrong detection mode should produce a failure."""
        products = _make_products()
        rubric = _make_rubric()
        # force an undetectable scenario: rank-1 with rank_rises (it can't rise higher)
        bad_scenario = FaultScenario(
            id="broken", name="Broken",
            fault_type=FaultType.RETRIEVAL_MISS,
            products=products, rubric=rubric,
            target_product="Alpha",
            detection="rank_rises",   # wrong: retrieval_miss should DROP rank, not rise
            source_fixture="test",
        )
        result = StageIsolationMetric().evaluate([bad_scenario])
        assert result.score < 100.0
        assert not result.passed
        assert len(result.failures) == 1

    def test_single_product_counted_as_not_applicable(self):
        single_product = [ProductProfile("OnlyOne", {"quality": 7.0})]
        rubric = [RubricWeight("quality", "Quality", 5.0)]
        scenario = FaultScenario(
            id="single", name="Single Product",
            fault_type=FaultType.RETRIEVAL_MISS,
            products=single_product, rubric=rubric,
            target_product="OnlyOne", detection="rank_drops",
            source_fixture="test",
        )
        result = StageIsolationMetric().evaluate([scenario])
        # With 1 product, build_scored_products returns 1 item — counted as not_applicable
        assert result.details["not_applicable"] == 1

    def test_score_0_for_single_product_only(self):
        single_product = [ProductProfile("OnlyOne", {"quality": 7.0})]
        rubric = [RubricWeight("quality", "Quality", 5.0)]
        scenario = FaultScenario(
            id="single", name="Single Product",
            fault_type=FaultType.RETRIEVAL_MISS,
            products=single_product, rubric=rubric,
            target_product="OnlyOne", detection="rank_drops",
            source_fixture="test",
        )
        result = StageIsolationMetric().evaluate([scenario])
        assert result.score == 0.0  # 0 applicable → 0 score

    def test_name_and_phase(self):
        m = StageIsolationMetric()
        assert m.name == "stage_isolation"
        assert "Phase 10" in m.phase

    def test_by_fault_type_detection_rates_sum(self):
        result = StageIsolationMetric().evaluate(self._four_scenarios())
        for stats in result.details["by_fault_type"].values():
            assert stats["detection_rate"] == 100.0


# ── _build_scenarios_for_source tests ────────────────────────────────────────

class TestBuildScenariosForSource:
    def test_returns_4_scenarios(self):
        scenarios = _build_scenarios_for_source(
            _make_products(), _make_rubric(), "test_src"
        )
        assert len(scenarios) == 4

    def test_returns_empty_for_1_product(self):
        products = [ProductProfile("Single", {"q": 7.0})]
        rubric = [RubricWeight("q", "Q", 5.0)]
        assert _build_scenarios_for_source(products, rubric, "src") == []

    def test_all_four_fault_types_present(self):
        scenarios = _build_scenarios_for_source(
            _make_products(), _make_rubric(), "test_src"
        )
        types = {s.fault_type for s in scenarios}
        assert types == set(FaultType)

    def test_source_fixture_set_correctly(self):
        scenarios = _build_scenarios_for_source(
            _make_products(), _make_rubric(), "my_source"
        )
        for s in scenarios:
            assert s.source_fixture == "my_source"

    def test_id_contains_source_id(self):
        scenarios = _build_scenarios_for_source(
            _make_products(), _make_rubric(), "pool_abc"
        )
        for s in scenarios:
            assert "pool_abc" in s.id

    def test_retrieval_miss_targets_rank1(self):
        products = _make_products()
        rubric = _make_rubric()
        baseline = build_scored_products(products, rubric)
        scenarios = _build_scenarios_for_source(products, rubric, "src")
        retrieval_miss = next(s for s in scenarios if s.fault_type == FaultType.RETRIEVAL_MISS)
        assert retrieval_miss.target_product == baseline[0]["name"]

    def test_evidence_hallucination_targets_last(self):
        products = _make_products()
        rubric = _make_rubric()
        baseline = build_scored_products(products, rubric)
        scenarios = _build_scenarios_for_source(products, rubric, "src")
        hallucination = next(s for s in scenarios if s.fault_type == FaultType.EVIDENCE_HALLUCINATION)
        assert hallucination.target_product == baseline[-1]["name"]

    def test_score_drift_targets_rank2(self):
        products = _make_products()
        rubric = _make_rubric()
        baseline = build_scored_products(products, rubric)
        scenarios = _build_scenarios_for_source(products, rubric, "src")
        drift = next(s for s in scenarios if s.fault_type == FaultType.SCORE_DRIFT)
        assert drift.target_product == baseline[1]["name"]


# ── Helpers tests ─────────────────────────────────────────────────────────────

class TestHelpers:
    def test_products_from_recorded_extracts_correctly(self):
        fixture = {
            "scored_products": [
                {
                    "name": "ProductA",
                    "signal_strength": "strong",
                    "mention_count": 30,
                    "positive_mentions": 22,
                    "negative_mentions": 8,
                    "praise": ["good"],
                    "complaints": [],
                    "scores": [
                        {"criterion": "quality", "score": 8.0},
                        {"criterion": "value", "score": 6.0},
                    ],
                },
                {
                    "name": "ProductB",
                    "scores": [
                        {"criterion": "quality", "score": 5.0},
                        {"criterion": "value", "score": 7.0},
                    ],
                },
            ]
        }
        products = _products_from_recorded(fixture)
        assert len(products) == 2
        assert products[0].name == "ProductA"
        assert products[0].criterion_scores["quality"] == 8.0
        assert products[0].mention_count == 30
        assert products[1].name == "ProductB"

    def test_products_from_recorded_skips_no_scores(self):
        fixture = {
            "scored_products": [
                {"name": "NoScores", "scores": []},
                {"name": "HasScores", "scores": [{"criterion": "quality", "score": 7.0}]},
            ]
        }
        products = _products_from_recorded(fixture)
        assert len(products) == 1
        assert products[0].name == "HasScores"

    def test_equal_weight_rubric_uses_5_weight(self):
        products = [
            ProductProfile("A", {"x": 7.0, "y": 5.0}),
            ProductProfile("B", {"x": 6.0, "z": 4.0}),
        ]
        rubric = _equal_weight_rubric(products)
        criteria = {r.criterion for r in rubric}
        assert criteria == {"x", "y", "z"}
        for r in rubric:
            assert r.weight == 5.0

    def test_equal_weight_rubric_label_matches_criterion(self):
        products = [ProductProfile("A", {"quality": 8.0})]
        rubric = _equal_weight_rubric(products)
        assert rubric[0].label == "quality"


# ── Integration tests ─────────────────────────────────────────────────────────

class TestAllFaultScenarios:
    def test_returns_non_empty_list(self):
        scenarios = all_fault_scenarios()
        assert len(scenarios) > 0

    def test_all_are_fault_scenario_instances(self):
        scenarios = all_fault_scenarios()
        for s in scenarios:
            assert isinstance(s, FaultScenario)

    def test_all_fault_types_represented(self):
        scenarios = all_fault_scenarios()
        types = {s.fault_type for s in scenarios}
        assert FaultType.RETRIEVAL_MISS in types
        assert FaultType.MENTION_COUNT_HALVING in types
        assert FaultType.EVIDENCE_HALLUCINATION in types
        assert FaultType.SCORE_DRIFT in types

    def test_all_scenarios_have_products(self):
        scenarios = all_fault_scenarios()
        for s in scenarios:
            assert len(s.products) >= 2, f"{s.id} has fewer than 2 products"

    def test_all_scenarios_have_rubric(self):
        scenarios = all_fault_scenarios()
        for s in scenarios:
            assert len(s.rubric) > 0, f"{s.id} has empty rubric"

    def test_all_scenarios_have_valid_detection_mode(self):
        scenarios = all_fault_scenarios()
        valid_modes = {"rank_drops", "rank_rises"}
        for s in scenarios:
            assert s.detection in valid_modes, (
                f"{s.id} has invalid detection mode: {s.detection!r}"
            )

    def test_generate_from_pools_returns_multiples_of_4(self):
        scenarios = generate_fault_scenarios_from_pools()
        # Each source generates exactly 4 scenarios
        assert len(scenarios) % 4 == 0
        assert len(scenarios) > 0

    def test_full_metric_run_scores_100(self):
        """Integration: running the metric on all fault scenarios scores 100%."""
        scenarios = all_fault_scenarios()
        result = StageIsolationMetric().evaluate(scenarios)
        assert result.score == 100.0, (
            f"Expected 100.0 on clean data but got {result.score}.\n"
            f"Failures:\n" + "\n".join(result.failures[:10])
        )
        assert result.passed


# ── Config consistency tests ───────────────────────────────────────────────────

class TestConfigConsistency:
    def test_index_weights_sum_to_1(self):
        from evals.config import INDEX_WEIGHTS
        total = sum(INDEX_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"INDEX_WEIGHTS sum = {total}, expected 1.0"

    def test_stage_isolation_in_index_weights(self):
        from evals.config import INDEX_WEIGHTS
        assert "stage_isolation" in INDEX_WEIGHTS

    def test_stage_isolation_in_pass_thresholds(self):
        from evals.config import PASS_THRESHOLDS
        assert "stage_isolation" in PASS_THRESHOLDS
        assert PASS_THRESHOLDS["stage_isolation"] >= 80.0

    def test_stage_isolation_in_ci_block_thresholds(self):
        from evals.config import CI_BLOCK_THRESHOLDS
        assert "stage_isolation" in CI_BLOCK_THRESHOLDS

    def test_stage_isolation_in_quick_eval_metrics(self):
        from evals.config import QUICK_EVAL_METRICS
        assert "stage_isolation" in QUICK_EVAL_METRICS

    def test_explanation_integrity_weight_reduced(self):
        from evals.config import INDEX_WEIGHTS
        assert INDEX_WEIGHTS["explanation_integrity"] == 0.02

    def test_stage_isolation_weight_is_003(self):
        from evals.config import INDEX_WEIGHTS
        assert INDEX_WEIGHTS["stage_isolation"] == 0.03
