"""
End-to-end tests for the Conflict Detection eval harness (Phase 13).

Coverage:
  TestConflictScenarioDataclass  (9  tests) — dataclass fields + genuine_conflict
  TestProductPool                (12 tests) — product scores, pool invariants
  TestRubricBuilder              (7  tests) — _rubric() helper correctness
  TestBalancedRubricWinners      (10 tests) — engine picks expected winner per scenario
  TestExtremeRubricWinners       (20 tests) — each champion wins under single-criterion rubric
  TestConflictDetectionMetric    (14 tests) — MetricResult structure + score/pass
  TestMetricEdgeCases            (6  tests) — empty list, skip, partial failures
  TestConfigIntegration          (7  tests) — conflict_detection in config dicts
"""

from __future__ import annotations

import pytest

from evals.benchmarks.conflict_detection import (
    ConflictScenario,
    all_conflict_scenarios,
    _rubric,
    _CRITERIA,
    _CRITERIA_LABELS,
    _P,
)
from evals.metrics.conflict_detection import ConflictDetectionMetric, _extreme_rubric
from evals.engine import build_scored_products
from evals.config import (
    INDEX_WEIGHTS,
    PASS_THRESHOLDS,
    CI_BLOCK_THRESHOLDS,
    QUICK_EVAL_METRICS,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _top(products, rubric):
    ranked = build_scored_products(products, rubric)
    return ranked[0]["name"] if ranked else ""


def _score_for(products, rubric, name: str) -> float:
    ranked = build_scored_products(products, rubric)
    for r in ranked:
        if r["name"] == name:
            return r["weighted_total"]
    raise KeyError(name)


def _get_product(name: str):
    for p in _P:
        if p.name == name:
            return p
    raise KeyError(name)


# ─── TestConflictScenarioDataclass ────────────────────────────────────────────

class TestConflictScenarioDataclass:
    """Dataclass structure and the genuine_conflict property."""

    def test_all_conflict_scenarios_returns_ten(self):
        assert len(all_conflict_scenarios()) == 10

    def test_returns_new_list_each_call(self):
        a = all_conflict_scenarios()
        b = all_conflict_scenarios()
        assert a is not b
        assert a == b

    def test_every_scenario_has_unique_id(self):
        ids = [s.id for s in all_conflict_scenarios()]
        assert len(ids) == len(set(ids))

    def test_required_fields_present(self):
        for sc in all_conflict_scenarios():
            assert sc.id
            assert sc.name
            assert sc.description
            assert sc.tags
            assert sc.products
            assert sc.rubric_weights
            assert sc.expected_balanced_winner
            assert sc.primary_criterion
            assert sc.secondary_criterion
            assert sc.primary_champion
            assert sc.secondary_champion

    def test_genuine_conflict_true_when_champions_differ(self):
        for sc in all_conflict_scenarios():
            if sc.primary_champion != sc.secondary_champion:
                assert sc.genuine_conflict is True

    def test_genuine_conflict_false_when_champions_same(self):
        # S8 and S9 are specialist-wins scenarios; primary and secondary champion differ
        # so genuine_conflict is still True there.  Manually craft a case to verify False.
        scenarios = all_conflict_scenarios()
        # Build a fake scenario with same champion for both
        fake = ConflictScenario(
            id="fake", name="fake", description="", tags=[],
            products=_P,
            rubric_weights=_rubric({}),
            expected_balanced_winner="MidRange",
            primary_criterion="sound_quality",
            secondary_criterion="price_to_value",
            primary_champion="SoundKing",
            secondary_champion="SoundKing",  # same
        )
        assert fake.genuine_conflict is False

    def test_most_scenarios_are_genuine_conflicts(self):
        genuines = [s for s in all_conflict_scenarios() if s.genuine_conflict]
        assert len(genuines) >= 8

    def test_conflict_description_non_empty(self):
        for sc in all_conflict_scenarios():
            assert len(sc.conflict_description) > 10

    def test_products_list_contains_six_products(self):
        for sc in all_conflict_scenarios():
            assert len(sc.products) == 6

    def test_rubric_weights_has_five_entries(self):
        for sc in all_conflict_scenarios():
            assert len(sc.rubric_weights) == 5


# ─── TestProductPool ─────────────────────────────────────────────────────────

class TestProductPool:
    """The six purpose-built products have the right scores."""

    def test_pool_has_six_products(self):
        assert len(_P) == 6

    def test_product_names(self):
        names = {p.name for p in _P}
        assert names == {"SoundKing", "PricePick", "BatteryAce", "CallPro", "ComfortPlus", "MidRange"}

    def test_sound_king_scores(self):
        p = _get_product("SoundKing")
        assert p.criterion_scores["sound_quality"] == 9
        assert p.criterion_scores["price_to_value"] == 4
        assert p.criterion_scores["battery_life"] == 4
        assert p.criterion_scores["comfort"] == 4
        assert p.criterion_scores["call_quality"] == 4

    def test_mid_range_scores_all_seven(self):
        p = _get_product("MidRange")
        for c in _CRITERIA:
            assert p.criterion_scores[c] == 7, f"MidRange.{c} should be 7"

    def test_each_specialist_has_score_nine_on_own_criterion(self):
        mapping = {
            "SoundKing": "sound_quality",
            "PricePick": "price_to_value",
            "BatteryAce": "battery_life",
            "ComfortPlus": "comfort",
            "CallPro": "call_quality",
        }
        for name, criterion in mapping.items():
            p = _get_product(name)
            assert p.criterion_scores[criterion] == 9, f"{name} should score 9 on {criterion}"

    def test_each_specialist_scores_four_on_non_own_criteria(self):
        mapping = {
            "SoundKing": "sound_quality",
            "PricePick": "price_to_value",
            "BatteryAce": "battery_life",
            "ComfortPlus": "comfort",
            "CallPro": "call_quality",
        }
        for name, own in mapping.items():
            p = _get_product(name)
            for c in _CRITERIA:
                if c != own:
                    assert p.criterion_scores[c] == 4, f"{name}.{c} should be 4"

    def test_midrange_beats_specialist_pair_under_equal_weights(self):
        """Core invariant: 7+7=14 > 9+4=13 under equal weights."""
        rubric = _rubric({"sound_quality": 8, "price_to_value": 8})
        midrange_score = _score_for(_P, rubric, "MidRange")
        soundking_score = _score_for(_P, rubric, "SoundKing")
        pricepick_score = _score_for(_P, rubric, "PricePick")
        assert midrange_score > soundking_score
        assert midrange_score > pricepick_score

    def test_specialist_beats_midrange_under_extreme_single_criterion(self):
        """Invariant: specialist(9) > midrange(7) when only one criterion is weighted."""
        rubric = _rubric({"sound_quality": 10})
        soundking_score = _score_for(_P, rubric, "SoundKing")
        midrange_score = _score_for(_P, rubric, "MidRange")
        assert soundking_score > midrange_score

    def test_products_have_mention_counts(self):
        for p in _P:
            assert p.mention_count > 0

    def test_products_have_praise_and_complaints(self):
        for p in _P:
            assert len(p.praise) >= 1
            assert len(p.complaints) >= 1

    def test_signal_strength_values_valid(self):
        valid = {"strong", "moderate", "weak"}
        for p in _P:
            assert p.signal_strength in valid

    def test_criteria_labels_match_criteria_list(self):
        assert set(_CRITERIA_LABELS.keys()) == set(_CRITERIA)


# ─── TestRubricBuilder ────────────────────────────────────────────────────────

class TestRubricBuilder:
    """_rubric() helper always returns all 5 criteria."""

    def test_always_returns_five_entries(self):
        assert len(_rubric({"sound_quality": 5})) == 5
        assert len(_rubric({})) == 5
        assert len(_rubric({c: 8 for c in _CRITERIA})) == 5

    def test_specified_weights_applied(self):
        rubric = _rubric({"sound_quality": 9, "battery_life": 3})
        rw = {r.criterion: r.weight for r in rubric}
        assert rw["sound_quality"] == 9
        assert rw["battery_life"] == 3

    def test_unspecified_criteria_get_zero_weight(self):
        rubric = _rubric({"sound_quality": 8})
        rw = {r.criterion: r.weight for r in rubric}
        for c in _CRITERIA:
            if c != "sound_quality":
                assert rw[c] == 0.0

    def test_empty_weights_dict_all_zeros(self):
        rubric = _rubric({})
        for rw in rubric:
            assert rw.weight == 0.0

    def test_criterion_order_matches_criteria_list(self):
        rubric = _rubric({})
        assert [rw.criterion for rw in rubric] == _CRITERIA

    def test_labels_correct(self):
        rubric = _rubric({})
        for rw in rubric:
            assert rw.label == _CRITERIA_LABELS[rw.criterion]

    def test_full_weight_rubric_sums_correctly(self):
        weights = {c: float(i + 1) for i, c in enumerate(_CRITERIA)}
        rubric = _rubric(weights)
        total = sum(rw.weight for rw in rubric)
        assert total == sum(weights.values())


# ─── TestBalancedRubricWinners ─────────────────────────────────────────────────

class TestBalancedRubricWinners:
    """Engine selects the expected winner for each scenario's balanced rubric."""

    @pytest.fixture(autouse=True)
    def scenarios(self):
        self._scenarios = {s.id: s for s in all_conflict_scenarios()}

    def _winner(self, scenario_id: str) -> str:
        sc = self._scenarios[scenario_id]
        return _top(sc.products, sc.rubric_weights)

    def test_s1_sound_vs_price_balanced_winner(self):
        assert self._winner("conflict_sound_vs_price") == "MidRange"

    def test_s2_sound_vs_battery_balanced_winner(self):
        assert self._winner("conflict_sound_vs_battery") == "MidRange"

    def test_s3_sound_vs_calls_balanced_winner(self):
        assert self._winner("conflict_sound_vs_calls") == "MidRange"

    def test_s4_price_vs_battery_balanced_winner(self):
        assert self._winner("conflict_price_vs_battery") == "MidRange"

    def test_s5_price_vs_calls_balanced_winner(self):
        assert self._winner("conflict_price_vs_calls") == "MidRange"

    def test_s6_battery_vs_calls_balanced_winner(self):
        assert self._winner("conflict_battery_vs_calls") == "MidRange"

    def test_s7_three_way_balanced_winner(self):
        assert self._winner("conflict_three_way_sound_price_battery") == "MidRange"

    def test_s8_sound_dominant_specialist_wins(self):
        assert self._winner("conflict_sound_dominant") == "SoundKing"

    def test_s9_battery_dominant_specialist_wins(self):
        assert self._winner("conflict_battery_dominant") == "BatteryAce"

    def test_s10_calls_vs_comfort_balanced_winner(self):
        assert self._winner("conflict_calls_vs_comfort") == "MidRange"


# ─── TestExtremeRubricWinners ─────────────────────────────────────────────────

class TestExtremeRubricWinners:
    """Each champion wins when their criterion is the only one with weight."""

    @pytest.fixture(autouse=True)
    def scenarios(self):
        self._scenarios = {s.id: s for s in all_conflict_scenarios()}

    def _extreme_winner(self, scenario_id: str, criterion: str) -> str:
        sc = self._scenarios[scenario_id]
        rubric = _extreme_rubric(sc.rubric_weights, criterion)
        return _top(sc.products, rubric)

    # S1 — sound vs price
    def test_s1_primary_soundking_wins_extreme_sound(self):
        assert self._extreme_winner("conflict_sound_vs_price", "sound_quality") == "SoundKing"

    def test_s1_secondary_pricepick_wins_extreme_price(self):
        assert self._extreme_winner("conflict_sound_vs_price", "price_to_value") == "PricePick"

    # S2 — sound vs battery
    def test_s2_primary_soundking_wins_extreme_sound(self):
        assert self._extreme_winner("conflict_sound_vs_battery", "sound_quality") == "SoundKing"

    def test_s2_secondary_batteryace_wins_extreme_battery(self):
        assert self._extreme_winner("conflict_sound_vs_battery", "battery_life") == "BatteryAce"

    # S3 — sound vs calls
    def test_s3_primary_soundking_wins_extreme_sound(self):
        assert self._extreme_winner("conflict_sound_vs_calls", "sound_quality") == "SoundKing"

    def test_s3_secondary_callpro_wins_extreme_calls(self):
        assert self._extreme_winner("conflict_sound_vs_calls", "call_quality") == "CallPro"

    # S4 — price vs battery
    def test_s4_primary_pricepick_wins_extreme_price(self):
        assert self._extreme_winner("conflict_price_vs_battery", "price_to_value") == "PricePick"

    def test_s4_secondary_batteryace_wins_extreme_battery(self):
        assert self._extreme_winner("conflict_price_vs_battery", "battery_life") == "BatteryAce"

    # S5 — price vs calls
    def test_s5_primary_pricepick_wins_extreme_price(self):
        assert self._extreme_winner("conflict_price_vs_calls", "price_to_value") == "PricePick"

    def test_s5_secondary_callpro_wins_extreme_calls(self):
        assert self._extreme_winner("conflict_price_vs_calls", "call_quality") == "CallPro"

    # S6 — battery vs calls
    def test_s6_primary_batteryace_wins_extreme_battery(self):
        assert self._extreme_winner("conflict_battery_vs_calls", "battery_life") == "BatteryAce"

    def test_s6_secondary_callpro_wins_extreme_calls(self):
        assert self._extreme_winner("conflict_battery_vs_calls", "call_quality") == "CallPro"

    # S7 — three-way
    def test_s7_primary_soundking_wins_extreme_sound(self):
        assert self._extreme_winner("conflict_three_way_sound_price_battery", "sound_quality") == "SoundKing"

    def test_s7_secondary_pricepick_wins_extreme_price(self):
        assert self._extreme_winner("conflict_three_way_sound_price_battery", "price_to_value") == "PricePick"

    # S8 — sound dominant
    def test_s8_primary_soundking_wins_extreme_sound(self):
        assert self._extreme_winner("conflict_sound_dominant", "sound_quality") == "SoundKing"

    def test_s8_secondary_pricepick_wins_extreme_price(self):
        assert self._extreme_winner("conflict_sound_dominant", "price_to_value") == "PricePick"

    # S9 — battery dominant
    def test_s9_primary_batteryace_wins_extreme_battery(self):
        assert self._extreme_winner("conflict_battery_dominant", "battery_life") == "BatteryAce"

    def test_s9_secondary_comfortplus_wins_extreme_comfort(self):
        assert self._extreme_winner("conflict_battery_dominant", "comfort") == "ComfortPlus"

    # S10 — calls vs comfort
    def test_s10_primary_callpro_wins_extreme_calls(self):
        assert self._extreme_winner("conflict_calls_vs_comfort", "call_quality") == "CallPro"

    def test_s10_secondary_comfortplus_wins_extreme_comfort(self):
        assert self._extreme_winner("conflict_calls_vs_comfort", "comfort") == "ComfortPlus"


# ─── TestConflictDetectionMetric ─────────────────────────────────────────────

class TestConflictDetectionMetric:
    """ConflictDetectionMetric produces correct MetricResult."""

    @pytest.fixture(autouse=True)
    def result(self):
        scenarios = all_conflict_scenarios()
        self._result = ConflictDetectionMetric().evaluate(scenarios)

    def test_name_is_conflict_detection(self):
        assert self._result.name == "conflict_detection"

    def test_score_is_100_all_scenarios_pass(self):
        assert self._result.score == 100.0

    def test_passed_is_true(self):
        assert self._result.passed is True

    def test_no_failures(self):
        assert self._result.failures == []

    def test_pass_threshold_is_80(self):
        assert self._result.pass_threshold == 80.0

    def test_details_total_scenarios(self):
        assert self._result.details["total_scenarios"] == 10

    def test_details_rank_correct_count(self):
        assert self._result.details["rank_correct"] == 10

    def test_details_primary_wins_count(self):
        assert self._result.details["primary_wins"] == 10

    def test_details_secondary_wins_count(self):
        assert self._result.details["secondary_wins"] == 10

    def test_details_scenarios_list_length(self):
        assert len(self._result.details["scenarios"]) == 10

    def test_scenario_detail_has_required_keys(self):
        required = {
            "id", "name", "per_score", "rank_correct", "primary_wins",
            "secondary_wins", "balanced_winner", "expected_balanced_winner",
            "primary_winner", "primary_champion", "secondary_winner",
            "secondary_champion", "genuine_conflict", "tags",
        }
        for detail in self._result.details["scenarios"]:
            assert required.issubset(detail.keys()), f"Missing keys in {detail['id']}"

    def test_all_per_scores_are_100(self):
        for detail in self._result.details["scenarios"]:
            assert detail["per_score"] == 100.0, f"{detail['id']} per_score={detail['per_score']}"

    def test_genuine_conflict_count_in_details(self):
        assert self._result.details["genuine_conflict_scenarios"] >= 8

    def test_not_skipped(self):
        assert self._result.skipped is False


# ─── TestMetricEdgeCases ─────────────────────────────────────────────────────

class TestMetricEdgeCases:
    """Edge cases: empty input, skip, partial failures."""

    def test_empty_list_returns_skip(self):
        result = ConflictDetectionMetric().evaluate([])
        assert result.skipped is True
        assert "no conflict scenarios" in result.details.get("skipped_reason", "")

    def test_extreme_rubric_produces_five_entries(self):
        rubric = _rubric({"sound_quality": 8, "price_to_value": 8})
        extreme = _extreme_rubric(rubric, "sound_quality")
        assert len(extreme) == 5

    def test_extreme_rubric_dominant_has_weight_ten(self):
        rubric = _rubric({"sound_quality": 8, "price_to_value": 8})
        extreme = _extreme_rubric(rubric, "sound_quality")
        dom = next(r for r in extreme if r.criterion == "sound_quality")
        assert dom.weight == 10.0

    def test_extreme_rubric_non_dominant_zero_weight(self):
        rubric = _rubric({"sound_quality": 8, "price_to_value": 8})
        extreme = _extreme_rubric(rubric, "sound_quality")
        for r in extreme:
            if r.criterion != "sound_quality":
                assert r.weight == 0.0

    def test_partial_failure_reduces_score(self):
        """Inject a wrong expected winner — per_score drops to 60 for that scenario."""
        scenarios = all_conflict_scenarios()
        # Mutate the first scenario's expected_balanced_winner to something wrong
        sc = scenarios[0]
        bad = ConflictScenario(
            id=sc.id, name=sc.name, description=sc.description, tags=sc.tags,
            products=sc.products, rubric_weights=sc.rubric_weights,
            expected_balanced_winner="SoundKing",  # wrong
            primary_criterion=sc.primary_criterion,
            secondary_criterion=sc.secondary_criterion,
            primary_champion=sc.primary_champion,
            secondary_champion=sc.secondary_champion,
            conflict_description=sc.conflict_description,
        )
        modified = [bad] + scenarios[1:]
        result = ConflictDetectionMetric().evaluate(modified)
        # First scenario scores 0×0.40 + 1×0.30 + 1×0.30 = 60; rest still 100
        expected = round((60.0 + 9 * 100.0) / 10, 1)
        assert result.score == expected
        assert result.passed is True  # 96 > 80

    def test_partial_failure_produces_failure_message(self):
        scenarios = all_conflict_scenarios()
        sc = scenarios[0]
        bad = ConflictScenario(
            id=sc.id, name=sc.name, description=sc.description, tags=sc.tags,
            products=sc.products, rubric_weights=sc.rubric_weights,
            expected_balanced_winner="SoundKing",  # wrong
            primary_criterion=sc.primary_criterion,
            secondary_criterion=sc.secondary_criterion,
            primary_champion=sc.primary_champion,
            secondary_champion=sc.secondary_champion,
        )
        result = ConflictDetectionMetric().evaluate([bad] + scenarios[1:])
        assert any("balanced winner" in f for f in result.failures)


# ─── TestConfigIntegration ────────────────────────────────────────────────────

class TestConfigIntegration:
    """conflict_detection is properly registered in all config dicts."""

    def test_in_index_weights(self):
        assert "conflict_detection" in INDEX_WEIGHTS

    def test_index_weights_sum_to_one(self):
        total = round(sum(INDEX_WEIGHTS.values()), 10)
        assert total == 1.0, f"INDEX_WEIGHTS sum to {total}, expected 1.0"

    def test_conflict_detection_weight_is_two_percent(self):
        assert INDEX_WEIGHTS["conflict_detection"] == 0.02

    def test_in_pass_thresholds(self):
        assert "conflict_detection" in PASS_THRESHOLDS
        assert PASS_THRESHOLDS["conflict_detection"] == 80.0

    def test_in_ci_block_thresholds(self):
        assert "conflict_detection" in CI_BLOCK_THRESHOLDS
        assert CI_BLOCK_THRESHOLDS["conflict_detection"] == 70.0

    def test_in_quick_eval_metrics(self):
        assert "conflict_detection" in QUICK_EVAL_METRICS

    def test_explanation_integrity_weight_reduced(self):
        # Weight was 0.02; reduced to 0.01 to make room for conflict_detection
        assert INDEX_WEIGHTS["explanation_integrity"] == 0.01

    def test_score_calibration_weight_reduced(self):
        # Weight was 0.02; reduced to 0.01 to make room for conflict_detection
        assert INDEX_WEIGHTS["score_calibration"] == 0.01
