"""
End-to-end tests for the Mention Popularity Bias eval harness (Phase 14).

Coverage:
  TestBiasScenarioDataclass      (10 tests) — dataclass fields + properties
  TestProductPool                (13 tests) — product scores, quality ordering
  TestRubricBuilder              ( 7 tests) — _rubric helper
  TestBaselineProductBuilding    ( 9 tests) — _baseline_products, _biased helpers
  TestScoreInvariance            (10 tests) — weighted_totals identical per scenario
  TestRankOneStability           (10 tests) — rank-1 winner unchanged per scenario
  TestTopThreeStability          (10 tests) — top-3 order unchanged per scenario
  TestMentionPopularityBiasMetric(14 tests) — MetricResult structure and correctness
  TestMetricEdgeCases            ( 8 tests) — empty list, skip, partial failures
  TestConfigIntegration          ( 8 tests) — weights, thresholds, QUICK_EVAL_METRICS
"""

from __future__ import annotations

import pytest

from evals.benchmarks.mention_popularity_bias import (
    BiasScenario,
    all_bias_scenarios,
    _rubric,
    _CRITERIA,
    _CRITERIA_LABELS,
    _SCORES,
    _BASELINE_MENTIONS,
    _BALANCED_RUBRIC,
    _baseline_products,
    _biased,
    _make_product,
)
from evals.metrics.mention_popularity_bias import (
    MentionPopularityBiasMetric,
    _rank1,
    _top3,
    _weighted_totals,
)
from evals.engine import build_scored_products
from evals.config import (
    INDEX_WEIGHTS,
    PASS_THRESHOLDS,
    CI_BLOCK_THRESHOLDS,
    QUICK_EVAL_METRICS,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _score(products, rubric, name: str) -> float:
    ranked = build_scored_products(products, rubric)
    for r in ranked:
        if r["name"] == name:
            return r["weighted_total"]
    raise KeyError(name)


def _get_scenario(sid: str) -> BiasScenario:
    for s in all_bias_scenarios():
        if s.id == sid:
            return s
    raise KeyError(sid)


# ─── TestBiasScenarioDataclass ────────────────────────────────────────────────

class TestBiasScenarioDataclass:
    """BiasScenario dataclass structure and public properties."""

    def test_all_bias_scenarios_returns_ten(self):
        assert len(all_bias_scenarios()) == 10

    def test_returns_fresh_list_each_call(self):
        a = all_bias_scenarios()
        b = all_bias_scenarios()
        assert a is not b
        assert len(a) == len(b)

    def test_every_scenario_has_unique_id(self):
        ids = [s.id for s in all_bias_scenarios()]
        assert len(ids) == len(set(ids))

    def test_required_fields_present(self):
        for s in all_bias_scenarios():
            assert s.id
            assert s.name
            assert s.description
            assert s.tags
            assert s.baseline_products
            assert s.biased_products
            assert s.rubric_weights
            assert s.expected_rank_1
            assert s.expected_top_3
            assert s.bias_type

    def test_n_products_property_is_five(self):
        for s in all_bias_scenarios():
            assert s.n_products == 5

    def test_baseline_and_biased_same_length(self):
        for s in all_bias_scenarios():
            assert len(s.baseline_products) == len(s.biased_products)

    def test_biased_product_names_property(self):
        for s in all_bias_scenarios():
            names = s.biased_product_names
            assert len(names) == 5
            assert "QualityKing" in names

    def test_expected_rank_1_is_quality_king(self):
        for s in all_bias_scenarios():
            assert s.expected_rank_1 == "QualityKing"

    def test_expected_top_3_order(self):
        for s in all_bias_scenarios():
            assert s.expected_top_3 == ["QualityKing", "SolidSecond", "MidProduct"]

    def test_bias_descriptions_non_empty(self):
        for s in all_bias_scenarios():
            assert len(s.bias_description) > 10


# ─── TestProductPool ─────────────────────────────────────────────────────────

class TestProductPool:
    """Product scores and quality ordering."""

    def test_five_products_defined(self):
        assert len(_SCORES) == 5

    def test_product_names(self):
        assert set(_SCORES.keys()) == {
            "QualityKing", "SolidSecond", "MidProduct", "WeakEntry", "PopularLow"
        }

    def test_quality_king_has_highest_sound_score(self):
        assert _SCORES["QualityKing"]["sound_quality"] == 9

    def test_popular_low_has_lowest_scores(self):
        for crit in _CRITERIA:
            assert _SCORES["PopularLow"][crit] <= _SCORES["WeakEntry"][crit]

    def test_quality_king_wins_balanced_rubric(self):
        products = _baseline_products()
        ranked = build_scored_products(products, _BALANCED_RUBRIC)
        assert ranked[0]["name"] == "QualityKing"

    def test_solid_second_is_rank_two(self):
        products = _baseline_products()
        ranked = build_scored_products(products, _BALANCED_RUBRIC)
        assert ranked[1]["name"] == "SolidSecond"

    def test_popular_low_is_rank_five(self):
        products = _baseline_products()
        ranked = build_scored_products(products, _BALANCED_RUBRIC)
        assert ranked[-1]["name"] == "PopularLow"

    def test_quality_king_weighted_total_320(self):
        products = _baseline_products()
        assert _score(products, _BALANCED_RUBRIC, "QualityKing") == 320.0

    def test_solid_second_weighted_total_304(self):
        products = _baseline_products()
        assert _score(products, _BALANCED_RUBRIC, "SolidSecond") == 304.0

    def test_mid_product_weighted_total_280(self):
        products = _baseline_products()
        assert _score(products, _BALANCED_RUBRIC, "MidProduct") == 280.0

    def test_weak_entry_weighted_total_216(self):
        products = _baseline_products()
        assert _score(products, _BALANCED_RUBRIC, "WeakEntry") == 216.0

    def test_popular_low_weighted_total_136(self):
        products = _baseline_products()
        assert _score(products, _BALANCED_RUBRIC, "PopularLow") == 136.0

    def test_quality_gap_winner_to_rank5(self):
        products = _baseline_products()
        winner = _score(products, _BALANCED_RUBRIC, "QualityKing")
        last = _score(products, _BALANCED_RUBRIC, "PopularLow")
        assert winner - last > 100


# ─── TestRubricBuilder ────────────────────────────────────────────────────────

class TestRubricBuilder:
    """_rubric() helper correctness."""

    def test_always_returns_five_entries(self):
        assert len(_rubric({})) == 5
        assert len(_rubric({"sound_quality": 8})) == 5
        assert len(_rubric({c: 5 for c in _CRITERIA})) == 5

    def test_specified_weights_applied(self):
        rubric = _rubric({"sound_quality": 9, "battery_life": 2})
        rw = {r.criterion: r.weight for r in rubric}
        assert rw["sound_quality"] == 9
        assert rw["battery_life"] == 2

    def test_missing_criteria_get_zero_weight(self):
        rubric = _rubric({"sound_quality": 8})
        rw = {r.criterion: r.weight for r in rubric}
        for c in _CRITERIA:
            if c != "sound_quality":
                assert rw[c] == 0.0

    def test_balanced_rubric_all_weights_eight(self):
        for rw in _BALANCED_RUBRIC:
            assert rw.weight == 8.0

    def test_criterion_order_matches_criteria_list(self):
        rubric = _rubric({})
        assert [rw.criterion for rw in rubric] == _CRITERIA

    def test_labels_match_criteria_labels(self):
        rubric = _rubric({})
        for rw in rubric:
            assert rw.label == _CRITERIA_LABELS[rw.criterion]

    def test_criteria_labels_complete(self):
        assert set(_CRITERIA_LABELS.keys()) == set(_CRITERIA)


# ─── TestBaselineProductBuilding ─────────────────────────────────────────────

class TestBaselineProductBuilding:
    """_baseline_products and _biased helpers."""

    def test_baseline_products_returns_five(self):
        assert len(_baseline_products()) == 5

    def test_baseline_products_correct_mention_counts(self):
        products = {p.name: p for p in _baseline_products()}
        for name, (mc, pos, neg) in _BASELINE_MENTIONS.items():
            assert products[name].mention_count == mc
            assert products[name].positive_mentions == pos
            assert products[name].negative_mentions == neg

    def test_baseline_criterion_scores_unchanged(self):
        for p in _baseline_products():
            for c in _CRITERIA:
                assert p.criterion_scores[c] == _SCORES[p.name][c]

    def test_biased_overrides_specific_product(self):
        products = {p.name: p for p in _biased({"PopularLow": (99999, 80000, 19999)})}
        assert products["PopularLow"].mention_count == 99999
        assert products["QualityKing"].mention_count == _BASELINE_MENTIONS["QualityKing"][0]

    def test_biased_criterion_scores_never_change(self):
        biased = _biased({name: (0, 0, 0) for name in _BASELINE_MENTIONS})
        for p in biased:
            for c in _CRITERIA:
                assert p.criterion_scores[c] == _SCORES[p.name][c]

    def test_make_product_correct_criterion_scores(self):
        p = _make_product("QualityKing", 45, 35, 10)
        assert p.criterion_scores["sound_quality"] == 9
        assert p.mention_count == 45
        assert p.positive_mentions == 35

    def test_make_product_with_zero_mentions(self):
        p = _make_product("QualityKing", 0, 0, 0)
        assert p.criterion_scores["sound_quality"] == 9  # scores unchanged
        assert p.mention_count == 0

    def test_biased_returns_five_products(self):
        biased = _biased({"QualityKing": (1, 1, 0)})
        assert len(biased) == 5

    def test_biased_product_names_match_baseline(self):
        baseline_names = [p.name for p in _baseline_products()]
        biased_names = [p.name for p in _biased({})]
        assert baseline_names == biased_names


# ─── TestScoreInvariance ──────────────────────────────────────────────────────

class TestScoreInvariance:
    """weighted_total is bit-identical between baseline and biased for every scenario."""

    @pytest.fixture(autouse=True)
    def scenarios(self):
        self._scenarios = {s.id: s for s in all_bias_scenarios()}

    def _check_invariant(self, scenario_id: str) -> bool:
        sc = self._scenarios[scenario_id]
        base_totals = _weighted_totals(sc.baseline_products, sc.rubric_weights)
        bias_totals = _weighted_totals(sc.biased_products, sc.rubric_weights)
        return base_totals == bias_totals

    def test_s1_inversion_score_invariant(self):
        assert self._check_invariant("bias_mention_inversion")

    def test_s2_flood_loser_score_invariant(self):
        assert self._check_invariant("bias_flood_loser")

    def test_s3_zero_winner_score_invariant(self):
        assert self._check_invariant("bias_zero_winner_mentions")

    def test_s4_all_zero_score_invariant(self):
        assert self._check_invariant("bias_all_zero_mentions")

    def test_s5_uniform_high_score_invariant(self):
        assert self._check_invariant("bias_uniform_high_mentions")

    def test_s6_winner_starved_score_invariant(self):
        assert self._check_invariant("bias_winner_starved")

    def test_s7_positive_flood_loser_score_invariant(self):
        assert self._check_invariant("bias_positive_flood_loser")

    def test_s8_negative_flood_winner_score_invariant(self):
        assert self._check_invariant("bias_negative_flood_winner")

    def test_s9_tail_coalition_score_invariant(self):
        assert self._check_invariant("bias_tail_coalition_boost")

    def test_s10_sentiment_swap_score_invariant(self):
        assert self._check_invariant("bias_sentiment_swap")


# ─── TestRankOneStability ─────────────────────────────────────────────────────

class TestRankOneStability:
    """Rank-1 winner is QualityKing under biased mention counts for every scenario."""

    @pytest.fixture(autouse=True)
    def scenarios(self):
        self._scenarios = {s.id: s for s in all_bias_scenarios()}

    def _biased_rank1(self, scenario_id: str) -> str:
        sc = self._scenarios[scenario_id]
        return _rank1(sc.biased_products, sc.rubric_weights)

    def test_s1_inversion_rank1_stable(self):
        assert self._biased_rank1("bias_mention_inversion") == "QualityKing"

    def test_s2_flood_loser_rank1_stable(self):
        assert self._biased_rank1("bias_flood_loser") == "QualityKing"

    def test_s3_zero_winner_rank1_stable(self):
        assert self._biased_rank1("bias_zero_winner_mentions") == "QualityKing"

    def test_s4_all_zero_rank1_stable(self):
        assert self._biased_rank1("bias_all_zero_mentions") == "QualityKing"

    def test_s5_uniform_high_rank1_stable(self):
        assert self._biased_rank1("bias_uniform_high_mentions") == "QualityKing"

    def test_s6_winner_starved_rank1_stable(self):
        assert self._biased_rank1("bias_winner_starved") == "QualityKing"

    def test_s7_positive_flood_loser_rank1_stable(self):
        assert self._biased_rank1("bias_positive_flood_loser") == "QualityKing"

    def test_s8_negative_flood_winner_rank1_stable(self):
        assert self._biased_rank1("bias_negative_flood_winner") == "QualityKing"

    def test_s9_tail_coalition_rank1_stable(self):
        assert self._biased_rank1("bias_tail_coalition_boost") == "QualityKing"

    def test_s10_sentiment_swap_rank1_stable(self):
        assert self._biased_rank1("bias_sentiment_swap") == "QualityKing"


# ─── TestTopThreeStability ────────────────────────────────────────────────────

class TestTopThreeStability:
    """Full top-3 order is unchanged under biased mention counts for every scenario."""

    _EXPECTED_TOP_3 = ["QualityKing", "SolidSecond", "MidProduct"]

    @pytest.fixture(autouse=True)
    def scenarios(self):
        self._scenarios = {s.id: s for s in all_bias_scenarios()}

    def _biased_top3(self, scenario_id: str) -> list[str]:
        sc = self._scenarios[scenario_id]
        return _top3(sc.biased_products, sc.rubric_weights)

    def test_s1_inversion_top3_stable(self):
        assert self._biased_top3("bias_mention_inversion") == self._EXPECTED_TOP_3

    def test_s2_flood_loser_top3_stable(self):
        assert self._biased_top3("bias_flood_loser") == self._EXPECTED_TOP_3

    def test_s3_zero_winner_top3_stable(self):
        assert self._biased_top3("bias_zero_winner_mentions") == self._EXPECTED_TOP_3

    def test_s4_all_zero_top3_stable(self):
        assert self._biased_top3("bias_all_zero_mentions") == self._EXPECTED_TOP_3

    def test_s5_uniform_high_top3_stable(self):
        assert self._biased_top3("bias_uniform_high_mentions") == self._EXPECTED_TOP_3

    def test_s6_winner_starved_top3_stable(self):
        assert self._biased_top3("bias_winner_starved") == self._EXPECTED_TOP_3

    def test_s7_positive_flood_loser_top3_stable(self):
        assert self._biased_top3("bias_positive_flood_loser") == self._EXPECTED_TOP_3

    def test_s8_negative_flood_winner_top3_stable(self):
        assert self._biased_top3("bias_negative_flood_winner") == self._EXPECTED_TOP_3

    def test_s9_tail_coalition_top3_stable(self):
        assert self._biased_top3("bias_tail_coalition_boost") == self._EXPECTED_TOP_3

    def test_s10_sentiment_swap_top3_stable(self):
        assert self._biased_top3("bias_sentiment_swap") == self._EXPECTED_TOP_3


# ─── TestMentionPopularityBiasMetric ─────────────────────────────────────────

class TestMentionPopularityBiasMetric:
    """MentionPopularityBiasMetric produces correct MetricResult."""

    @pytest.fixture(autouse=True)
    def result(self):
        self._result = MentionPopularityBiasMetric().evaluate(all_bias_scenarios())

    def test_name_is_mention_popularity_bias(self):
        assert self._result.name == "mention_popularity_bias"

    def test_score_is_100(self):
        assert self._result.score == 100.0

    def test_passed_is_true(self):
        assert self._result.passed is True

    def test_no_failures(self):
        assert self._result.failures == []

    def test_pass_threshold_is_85(self):
        assert self._result.pass_threshold == 85.0

    def test_not_skipped(self):
        assert self._result.skipped is False

    def test_details_total_scenarios(self):
        assert self._result.details["total_scenarios"] == 10

    def test_details_score_invariant_passes(self):
        assert self._result.details["score_invariant_passes"] == 10

    def test_details_rank1_stable_passes(self):
        assert self._result.details["rank1_stable_passes"] == 10

    def test_details_top3_stable_passes(self):
        assert self._result.details["top3_stable_passes"] == 10

    def test_scenario_details_list_length(self):
        assert len(self._result.details["scenarios"]) == 10

    def test_scenario_detail_required_keys(self):
        required = {
            "id", "name", "bias_type", "per_score", "score_invariant",
            "rank1_stable", "top3_stable", "baseline_rank1", "biased_rank1",
            "expected_rank_1", "baseline_top3", "biased_top3", "expected_top_3",
            "invariant_failures", "tags",
        }
        for detail in self._result.details["scenarios"]:
            assert required.issubset(detail.keys()), f"Missing keys in {detail['id']}"

    def test_all_per_scores_are_100(self):
        for detail in self._result.details["scenarios"]:
            assert detail["per_score"] == 100.0, f"{detail['id']} per_score={detail['per_score']}"


# ─── TestMetricEdgeCases ─────────────────────────────────────────────────────

class TestMetricEdgeCases:
    """Edge cases: empty input, skip, partial failures."""

    def test_empty_list_returns_skip(self):
        result = MentionPopularityBiasMetric().evaluate([])
        assert result.skipped is True
        assert "no bias scenarios" in result.details.get("skipped_reason", "")

    def test_rank1_helper_returns_top_name(self):
        products = _baseline_products()
        assert _rank1(products, _BALANCED_RUBRIC) == "QualityKing"

    def test_top3_helper_returns_three_names(self):
        products = _baseline_products()
        result = _top3(products, _BALANCED_RUBRIC)
        assert len(result) == 3
        assert result[0] == "QualityKing"

    def test_weighted_totals_helper_returns_all_products(self):
        products = _baseline_products()
        totals = _weighted_totals(products, _BALANCED_RUBRIC)
        assert set(totals.keys()) == {"QualityKing", "SolidSecond", "MidProduct", "WeakEntry", "PopularLow"}

    def test_partial_failure_score_invariant_reduces_score(self):
        """Inject a biased product with modified criterion_scores — score_invariant fails."""
        from copy import deepcopy
        from evals.benchmarks.base import ProductProfile
        scenarios = all_bias_scenarios()
        sc = scenarios[0]
        # Modify one biased product's criterion score to break score_invariant
        bad_biased = []
        for p in sc.biased_products:
            if p.name == "QualityKing":
                bad = ProductProfile(
                    name=p.name,
                    criterion_scores={**p.criterion_scores, "sound_quality": 8.0},  # changed!
                    mention_count=p.mention_count,
                    positive_mentions=p.positive_mentions,
                    negative_mentions=p.negative_mentions,
                    praise=p.praise,
                    complaints=p.complaints,
                )
                bad_biased.append(bad)
            else:
                bad_biased.append(p)
        bad_scenario = BiasScenario(
            id=sc.id, name=sc.name, description=sc.description, tags=sc.tags,
            baseline_products=sc.baseline_products,
            biased_products=bad_biased,
            rubric_weights=sc.rubric_weights,
            expected_rank_1=sc.expected_rank_1,
            expected_top_3=sc.expected_top_3,
            bias_type=sc.bias_type,
        )
        modified = [bad_scenario] + scenarios[1:]
        result = MentionPopularityBiasMetric().evaluate(modified)
        # First scenario: score_invariant=False(0), rank1_stable=True(0.30), top3_stable=True(0.20) → 50 pts
        expected_first = round((0.0 * 0.50 + 1.0 * 0.30 + 1.0 * 0.20) * 100.0, 1)
        overall = round((expected_first + 9 * 100.0) / 10, 1)
        assert result.score == overall

    def test_partial_failure_produces_failure_message(self):
        """Verify failure message is emitted when score_invariant fails."""
        from evals.benchmarks.base import ProductProfile
        scenarios = all_bias_scenarios()
        sc = scenarios[0]
        bad_biased = []
        for p in sc.biased_products:
            if p.name == "PopularLow":
                bad = ProductProfile(
                    name=p.name,
                    criterion_scores={**p.criterion_scores, "sound_quality": 9.0},  # inflated!
                    mention_count=p.mention_count,
                    positive_mentions=p.positive_mentions,
                    negative_mentions=p.negative_mentions,
                    praise=p.praise,
                    complaints=p.complaints,
                )
                bad_biased.append(bad)
            else:
                bad_biased.append(p)
        bad_scenario = BiasScenario(
            id=sc.id, name=sc.name, description=sc.description, tags=sc.tags,
            baseline_products=sc.baseline_products,
            biased_products=bad_biased,
            rubric_weights=sc.rubric_weights,
            expected_rank_1=sc.expected_rank_1,
            expected_top_3=sc.expected_top_3,
            bias_type=sc.bias_type,
        )
        result = MentionPopularityBiasMetric().evaluate([bad_scenario])
        assert any("score_invariant" in f for f in result.failures)

    def test_rank1_stable_failure_detected(self):
        """Inject wrong expected_rank_1 to trigger rank1_stable failure."""
        sc = all_bias_scenarios()[0]
        bad = BiasScenario(
            id=sc.id, name=sc.name, description=sc.description, tags=sc.tags,
            baseline_products=sc.baseline_products,
            biased_products=sc.biased_products,
            rubric_weights=sc.rubric_weights,
            expected_rank_1="PopularLow",  # wrong
            expected_top_3=sc.expected_top_3,
            bias_type=sc.bias_type,
        )
        result = MentionPopularityBiasMetric().evaluate([bad])
        assert not result.passed
        assert any("rank1_stable" in f for f in result.failures)


# ─── TestConfigIntegration ────────────────────────────────────────────────────

class TestConfigIntegration:
    """mention_popularity_bias is properly registered in all config dicts."""

    def test_in_index_weights(self):
        assert "mention_popularity_bias" in INDEX_WEIGHTS

    def test_index_weights_sum_to_one(self):
        total = round(sum(INDEX_WEIGHTS.values()), 10)
        assert total == 1.0, f"INDEX_WEIGHTS sum to {total}, expected 1.0"

    def test_mention_popularity_bias_weight_is_two_percent(self):
        assert INDEX_WEIGHTS["mention_popularity_bias"] == 0.02

    def test_recommendation_quality_remains_largest_weight(self):
        assert INDEX_WEIGHTS["recommendation_quality"] == max(INDEX_WEIGHTS.values())

    def test_in_pass_thresholds(self):
        assert "mention_popularity_bias" in PASS_THRESHOLDS
        assert PASS_THRESHOLDS["mention_popularity_bias"] == 85.0

    def test_in_ci_block_thresholds(self):
        assert "mention_popularity_bias" in CI_BLOCK_THRESHOLDS
        assert CI_BLOCK_THRESHOLDS["mention_popularity_bias"] == 75.0

    def test_in_quick_eval_metrics(self):
        assert "mention_popularity_bias" in QUICK_EVAL_METRICS

    def test_conflict_detection_weight_reduced(self):
        assert INDEX_WEIGHTS["conflict_detection"] == 0.01
