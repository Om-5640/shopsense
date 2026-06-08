"""
Tests for Phase 15: Nugget-Based Partial Credit for Human Alignment.

Coverage:
  TestNuggetDataclass              — 5  tests
  TestNuggetJudgmentDataclass      — 8  tests
  TestProductPool                  — 11 tests
  TestRubricBuilder                — 5  tests
  TestNuggetCreditFormula          — 12 tests
  TestNuggetJudgmentScores         — 8  tests  (one per judgment, expected score)
  TestNuggetAlignmentMetric        — 10 tests
  TestMetricEdgeCases              — 6  tests
  TestConfigIntegration            — 7  tests
                                   ─────────
  Total                            — 72 tests
"""

from __future__ import annotations

import pytest
from dataclasses import fields

from evals.benchmarks.nugget_alignment import (
    Nugget,
    NuggetJudgment,
    all_nugget_judgments,
    _SCORES,
    _ALL_PRODUCTS,
    _RUBRIC_AUDIO,
    _RUBRIC_BALANCED,
    _RUBRIC_ANC,
    _RUBRIC_VALUE,
    _RUBRIC_BATTERY,
    _rubric,
    _make_product,
    _CRITERIA,
)
from evals.benchmarks.base import ProductProfile, RubricWeight
from evals.engine import build_scored_products
from evals.metrics.nugget_alignment import (
    NuggetAlignmentMetric,
    _nugget_credit,
    _engine_top3,
)
from evals.metrics.base import MetricResult
from evals.config import (
    INDEX_WEIGHTS,
    PASS_THRESHOLDS,
    CI_BLOCK_THRESHOLDS,
    QUICK_EVAL_METRICS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_judgment(
    expert_rank_1: str = "AlphaChoice",
    expert_rank_2: str = "BetaChoice",
    expert_rank_3: str = "GammaChoice",
    nuggets: list[Nugget] | None = None,
    rubric=None,
) -> NuggetJudgment:
    if nuggets is None:
        nuggets = [Nugget("test nugget", ["AlphaChoice"])]
    if rubric is None:
        rubric = _RUBRIC_AUDIO
    return NuggetJudgment(
        id="test_jdg",
        name="Test Judgment",
        query="test query",
        products=list(_ALL_PRODUCTS),
        rubric_weights=rubric,
        expert_rank_1=expert_rank_1,
        expert_rank_2=expert_rank_2,
        expert_rank_3=expert_rank_3,
        nuggets=nuggets,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TestNuggetDataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestNuggetDataclass:
    def test_text_field_preserved(self):
        n = Nugget(text="AlphaChoice leads in sound quality")
        assert n.text == "AlphaChoice leads in sound quality"

    def test_products_mentioned_stored(self):
        n = Nugget(text="comparison", products_mentioned=["AlphaChoice", "BetaChoice"])
        assert n.products_mentioned == ["AlphaChoice", "BetaChoice"]

    def test_empty_products_mentioned_is_valid(self):
        n = Nugget(text="generic insight", products_mentioned=[])
        assert n.products_mentioned == []

    def test_products_mentioned_defaults_to_empty(self):
        n = Nugget(text="no products mentioned")
        assert n.products_mentioned == []

    def test_products_mentioned_is_mutable(self):
        n = Nugget(text="test")
        n.products_mentioned.append("AlphaChoice")
        assert "AlphaChoice" in n.products_mentioned


# ─────────────────────────────────────────────────────────────────────────────
# TestNuggetJudgmentDataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestNuggetJudgmentDataclass:
    def test_id_field_stored(self):
        jdg = _build_judgment()
        assert jdg.id == "test_jdg"

    def test_name_field_stored(self):
        jdg = _build_judgment()
        assert jdg.name == "Test Judgment"

    def test_query_field_stored(self):
        jdg = _build_judgment()
        assert jdg.query == "test query"

    def test_products_list_stored(self):
        jdg = _build_judgment()
        assert len(jdg.products) == 5

    def test_rubric_weights_stored(self):
        jdg = _build_judgment(rubric=_RUBRIC_AUDIO)
        assert len(jdg.rubric_weights) == 4

    def test_expert_rank_fields_accessible(self):
        jdg = _build_judgment(
            expert_rank_1="AlphaChoice",
            expert_rank_2="BetaChoice",
            expert_rank_3="GammaChoice",
        )
        assert jdg.expert_rank_1 == "AlphaChoice"
        assert jdg.expert_rank_2 == "BetaChoice"
        assert jdg.expert_rank_3 == "GammaChoice"

    def test_nuggets_list_stored(self):
        nuggets = [Nugget("n1"), Nugget("n2", ["A"])]
        jdg = _build_judgment(nuggets=nuggets)
        assert len(jdg.nuggets) == 2

    def test_n_nuggets_property(self):
        nuggets = [Nugget("a"), Nugget("b"), Nugget("c")]
        jdg = _build_judgment(nuggets=nuggets)
        assert jdg.n_nuggets == 3

    def test_expert_top3_property_returns_set(self):
        jdg = _build_judgment(
            expert_rank_1="AlphaChoice",
            expert_rank_2="BetaChoice",
            expert_rank_3="GammaChoice",
        )
        assert jdg.expert_top3 == {"AlphaChoice", "BetaChoice", "GammaChoice"}

    def test_expert_top3_property_is_set_of_three(self):
        jdg = _build_judgment(
            expert_rank_1="BetaChoice",
            expert_rank_2="GammaChoice",
            expert_rank_3="DeltaChoice",
        )
        assert len(jdg.expert_top3) == 3
        assert "DeltaChoice" in jdg.expert_top3


# ─────────────────────────────────────────────────────────────────────────────
# TestProductPool
# ─────────────────────────────────────────────────────────────────────────────

class TestProductPool:
    def test_pool_has_five_products(self):
        assert len(_ALL_PRODUCTS) == 5

    def test_all_product_names_present(self):
        names = {p.name for p in _ALL_PRODUCTS}
        expected = {"AlphaChoice", "BetaChoice", "GammaChoice", "DeltaChoice", "EpsilonChoice"}
        assert names == expected

    def test_alpha_choice_scores(self):
        scores = _SCORES["AlphaChoice"]
        assert scores["sound_quality"] == 9
        assert scores["noise_cancellation"] == 8
        assert scores["battery_life"] == 6
        assert scores["value_for_money"] == 5

    def test_beta_choice_scores(self):
        scores = _SCORES["BetaChoice"]
        assert scores["sound_quality"] == 8
        assert scores["noise_cancellation"] == 7
        assert scores["battery_life"] == 8
        assert scores["value_for_money"] == 7

    def test_delta_choice_high_value(self):
        scores = _SCORES["DeltaChoice"]
        assert scores["value_for_money"] == 9

    def test_epsilon_choice_lowest_quality(self):
        scores = _SCORES["EpsilonChoice"]
        assert all(v <= 4 for v in scores.values())

    def test_all_products_have_four_criteria(self):
        for name, scores in _SCORES.items():
            assert set(scores.keys()) == set(_CRITERIA), f"{name} missing criteria"

    def test_rubric1_top3(self):
        ranked = build_scored_products(list(_ALL_PRODUCTS), _RUBRIC_AUDIO)
        assert [r["name"] for r in ranked[:3]] == ["AlphaChoice", "BetaChoice", "GammaChoice"]

    def test_rubric2_top3(self):
        ranked = build_scored_products(list(_ALL_PRODUCTS), _RUBRIC_BALANCED)
        assert [r["name"] for r in ranked[:3]] == ["BetaChoice", "AlphaChoice", "GammaChoice"]

    def test_rubric4_top3(self):
        ranked = build_scored_products(list(_ALL_PRODUCTS), _RUBRIC_VALUE)
        assert [r["name"] for r in ranked[:3]] == ["BetaChoice", "GammaChoice", "DeltaChoice"]

    def test_rubric5_top3(self):
        ranked = build_scored_products(list(_ALL_PRODUCTS), _RUBRIC_BATTERY)
        assert [r["name"] for r in ranked[:3]] == ["BetaChoice", "GammaChoice", "AlphaChoice"]


# ─────────────────────────────────────────────────────────────────────────────
# TestRubricBuilder
# ─────────────────────────────────────────────────────────────────────────────

class TestRubricBuilder:
    def test_all_rubrics_have_four_weights(self):
        for rubric in [_RUBRIC_AUDIO, _RUBRIC_BALANCED, _RUBRIC_ANC, _RUBRIC_VALUE, _RUBRIC_BATTERY]:
            assert len(rubric) == 4

    def test_balanced_rubric_all_weights_equal(self):
        weights = {rw.weight for rw in _RUBRIC_BALANCED}
        assert weights == {6.0}

    def test_anc_rubric_nc_weight_is_dominant(self):
        nc_weight = next(rw.weight for rw in _RUBRIC_ANC if rw.criterion == "noise_cancellation")
        assert nc_weight == 8.0

    def test_value_rubric_value_weight_is_dominant(self):
        val_weight = next(rw.weight for rw in _RUBRIC_VALUE if rw.criterion == "value_for_money")
        assert val_weight == 9.0

    def test_battery_rubric_battery_weight_is_dominant(self):
        bat_weight = next(rw.weight for rw in _RUBRIC_BATTERY if rw.criterion == "battery_life")
        assert bat_weight == 9.0


# ─────────────────────────────────────────────────────────────────────────────
# TestNuggetCreditFormula
# ─────────────────────────────────────────────────────────────────────────────

class TestNuggetCreditFormula:
    # ── Engine top-3: {Alpha, Beta, Gamma}; Expert top-3: {Alpha, Beta, Gamma}

    def test_both_in_top3_returns_full_credit(self):
        credit = _nugget_credit(
            ["AlphaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 1.0

    def test_both_excluded_returns_full_credit(self):
        credit = _nugget_credit(
            ["DeltaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 1.0

    def test_expert_only_returns_zero(self):
        # DeltaChoice is in expert but not engine
        credit = _nugget_credit(
            ["DeltaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "DeltaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 0.0

    def test_engine_only_returns_half(self):
        # GammaChoice is in engine but not expert
        credit = _nugget_credit(
            ["GammaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "DeltaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 0.5

    def test_empty_products_mentioned_returns_neutral(self):
        credit = _nugget_credit(
            [],
            expert_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 0.8

    def test_two_products_both_agree_include(self):
        credit = _nugget_credit(
            ["AlphaChoice", "BetaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 1.0

    def test_two_products_both_agree_exclude(self):
        credit = _nugget_credit(
            ["DeltaChoice", "EpsilonChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 1.0

    def test_two_products_expert_miss_and_engine_over_include(self):
        # DeltaChoice: expert in, engine out → 0.0
        # GammaChoice: expert out, engine in → 0.5
        credit = _nugget_credit(
            ["DeltaChoice", "GammaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "DeltaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == pytest.approx(0.25)

    def test_all_engine_only_products(self):
        credit = _nugget_credit(
            ["GammaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "DeltaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 0.5

    def test_all_expert_only_products(self):
        credit = _nugget_credit(
            ["DeltaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "DeltaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == 0.0

    def test_mixed_four_products(self):
        # Alpha: both in → 1.0
        # Beta: both in → 1.0
        # Delta: expert in, engine out → 0.0
        # Gamma: engine in, expert out → 0.5
        credit = _nugget_credit(
            ["AlphaChoice", "BetaChoice", "DeltaChoice", "GammaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "DeltaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        )
        assert credit == pytest.approx((1.0 + 1.0 + 0.0 + 0.5) / 4)

    def test_single_product_both_agree_include_and_exclude_independent(self):
        # Verify the formula handles single products correctly for each case
        assert _nugget_credit(
            ["AlphaChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        ) == 1.0
        assert _nugget_credit(
            ["EpsilonChoice"],
            expert_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
            engine_top3={"AlphaChoice", "BetaChoice", "GammaChoice"},
        ) == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# TestNuggetJudgmentScores  (one test per hand-crafted judgment)
# ─────────────────────────────────────────────────────────────────────────────

class TestNuggetJudgmentScores:
    """
    Verify the pre-computed expected score for each of the 8 hand-crafted
    NuggetJudgments.  Running the metric on a single judgment gives us
    the exact per-judgment score.
    """

    def _score_single(self, judgment_id: str) -> float:
        jdg = next(j for j in all_nugget_judgments() if j.id == judgment_id)
        result = NuggetAlignmentMetric().evaluate([jdg])
        return result.score

    def test_nj1_audio_fidelity_expert_score(self):
        assert self._score_single("nj_audio_fidelity_expert") == 100.0

    def test_nj2_battery_optimizer_score(self):
        assert self._score_single("nj_battery_optimizer") == 100.0

    def test_nj3_balanced_partial_disagree_score(self):
        assert self._score_single("nj_balanced_partial_disagree") == 50.0

    def test_nj4_value_hunter_score(self):
        assert self._score_single("nj_value_hunter") == 100.0

    def test_nj5_anc_specialist_partial_score(self):
        assert self._score_single("nj_anc_specialist_partial") == 62.5

    def test_nj6_exclusion_precision_score(self):
        assert self._score_single("nj_exclusion_precision") == 100.0

    def test_nj7_unusual_expert_picks_score(self):
        assert self._score_single("nj_unusual_expert_picks") == 66.7

    def test_nj8_no_product_mentions_score(self):
        assert self._score_single("nj_no_product_mentions") == 80.0


# ─────────────────────────────────────────────────────────────────────────────
# TestNuggetAlignmentMetric
# ─────────────────────────────────────────────────────────────────────────────

class TestNuggetAlignmentMetric:
    def test_returns_metric_result(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert isinstance(result, MetricResult)

    def test_overall_score_is_82_4(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert result.score == 82.4

    def test_metric_passes(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert result.passed is True

    def test_metric_name(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert result.name == "nugget_alignment"

    def test_pass_threshold_from_config(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert result.pass_threshold == PASS_THRESHOLDS["nugget_alignment"]

    def test_details_total_judgments(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert result.details["total_judgments"] == 8

    def test_details_judgment_details_length(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert len(result.details["judgment_details"]) == 8

    def test_details_full_credit_judgments(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        # NJ1, NJ2, NJ4, NJ6 score 100.0 → 4 full-credit judgments
        assert result.details["full_credit_judgments"] == 4

    def test_details_partial_credit_judgments(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        # NJ3(50.0), NJ5(62.5), NJ7(66.7), NJ8(80.0) → 4 partial
        assert result.details["partial_credit_judgments"] == 4

    def test_not_skipped(self):
        result = NuggetAlignmentMetric().evaluate(all_nugget_judgments())
        assert result.skipped is False


# ─────────────────────────────────────────────────────────────────────────────
# TestMetricEdgeCases
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricEdgeCases:
    def test_empty_judgment_list_returns_skip(self):
        result = NuggetAlignmentMetric().evaluate([])
        assert result.skipped is True
        assert result.passed is True
        assert result.score == 0.0

    def test_empty_skip_reason_in_details(self):
        result = NuggetAlignmentMetric().evaluate([])
        assert "skipped_reason" in result.details

    def test_single_judgment_with_full_credit(self):
        jdg = _build_judgment(
            expert_rank_1="AlphaChoice",
            expert_rank_2="BetaChoice",
            expert_rank_3="GammaChoice",
            nuggets=[Nugget("AlphaChoice is top", ["AlphaChoice"])],
            rubric=_RUBRIC_AUDIO,
        )
        result = NuggetAlignmentMetric().evaluate([jdg])
        assert result.score == 100.0
        assert result.passed is True

    def test_all_expert_only_nuggets_produces_zero_score(self):
        # All nuggets mention a product only the expert picks (not engine)
        # Expert: [Alpha, Beta, Delta]; Engine: [Alpha, Beta, Gamma]
        jdg = _build_judgment(
            expert_rank_1="AlphaChoice",
            expert_rank_2="BetaChoice",
            expert_rank_3="DeltaChoice",
            nuggets=[
                Nugget("Delta is key", ["DeltaChoice"]),
                Nugget("Delta again", ["DeltaChoice"]),
            ],
            rubric=_RUBRIC_BALANCED,
        )
        result = NuggetAlignmentMetric().evaluate([jdg])
        assert result.score == 0.0

    def test_all_empty_product_nuggets_returns_80(self):
        jdg = _build_judgment(
            expert_rank_1="AlphaChoice",
            expert_rank_2="BetaChoice",
            expert_rank_3="GammaChoice",
            nuggets=[Nugget("generic"), Nugget("general"), Nugget("abstract")],
            rubric=_RUBRIC_AUDIO,
        )
        result = NuggetAlignmentMetric().evaluate([jdg])
        assert result.score == 80.0

    def test_failure_message_includes_judgment_id(self):
        # NJ3 has score 50.0 < 70.0, so it should appear in failures
        judgments = all_nugget_judgments()
        result = NuggetAlignmentMetric().evaluate(judgments)
        failure_ids = " ".join(result.failures)
        assert "nj_balanced_partial_disagree" in failure_ids


# ─────────────────────────────────────────────────────────────────────────────
# TestConfigIntegration
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigIntegration:
    def test_nugget_alignment_in_index_weights(self):
        assert "nugget_alignment" in INDEX_WEIGHTS

    def test_nugget_alignment_weight_is_two_percent(self):
        assert INDEX_WEIGHTS["nugget_alignment"] == 0.02

    def test_human_alignment_weight_reduced_to_three_percent(self):
        assert INDEX_WEIGHTS["human_alignment"] == 0.03

    def test_index_weights_sum_to_one(self):
        total = sum(INDEX_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_nugget_alignment_in_pass_thresholds(self):
        assert "nugget_alignment" in PASS_THRESHOLDS

    def test_nugget_alignment_in_ci_block_thresholds(self):
        assert "nugget_alignment" in CI_BLOCK_THRESHOLDS

    def test_nugget_alignment_in_quick_eval_metrics(self):
        assert "nugget_alignment" in QUICK_EVAL_METRICS
