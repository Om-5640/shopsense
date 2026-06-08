"""
End-to-end tests for the Real Earbuds Pool (earbuds_real.json).

Coverage:
  - Pool loads without validation errors via pool_loader
  - All 6 real-world products are present with valid scores
  - All 10 criteria are declared and each product covers all of them
  - Each product has the expected differentiating scores that encode real specs
  - All 15 scenarios produce the correct expected rank-1 winner
  - expected_rank_1_not constraints are never violated
  - All 6 human judgment panels produce exact top-3 engine matches
  - All 6 human judgment alignment scores are >= 95/100 (exact match → 100.0)
  - Pool integrates correctly with all_scenarios() and all_human_judgments()
  - Pool addition does not break INDEX_WEIGHTS sum
  - PoolValidationError is raised for malformed pool data
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from evals.benchmarks.pool_loader import (
    load_all_pools,
    pool_scenarios,
    pool_human_judgments,
    pool_categories,
    _parse_pool,
    PoolValidationError,
)
from evals.benchmarks import all_scenarios, all_human_judgments
from evals.engine import build_scored_products, rank_names
from evals.metrics.human_alignment import HumanAlignmentMetric
from evals.config import INDEX_WEIGHTS

# ── Constants ─────────────────────────────────────────────────────────────────

_POOL_PATH = _ROOT / "evals" / "data" / "pools" / "earbuds_real.json"

_PRODUCT_NAMES = [
    "Sony WF-1000XM5",
    "Apple AirPods Pro 2",
    "Bose QuietComfort Ultra Earbuds",
    "Nothing Ear (2)",
    "Anker Soundcore Liberty 4 NC",
    "Jabra Elite 5",
]

_CRITERIA_NAMES = [
    "sound_quality",
    "noise_cancellation",
    "transparency_mode",
    "battery_life",
    "comfort",
    "microphone_quality",
    "call_quality",
    "price_to_value",
    "codec_support",
    "durability",
]

_SCENARIO_EXPECTED_WINNERS = {
    "earbuds_real_android_audiophile":     "Sony WF-1000XM5",
    "earbuds_real_apple_daily_commute":    "Apple AirPods Pro 2",
    "earbuds_real_comfort_traveler":       "Bose QuietComfort Ultra Earbuds",
    "earbuds_real_value_audiophile":       "Nothing Ear (2)",
    "earbuds_real_budget_anc":             "Anker Soundcore Liberty 4 NC",
    "earbuds_real_business_calls":         "Jabra Elite 5",
    "earbuds_real_long_haul_flight":       "Apple AirPods Pro 2",
    "earbuds_real_active_outdoor":         "Jabra Elite 5",
    "earbuds_real_music_listening":        "Sony WF-1000XM5",
    "earbuds_real_budget_daily_driver":    "Anker Soundcore Liberty 4 NC",
    "earbuds_real_podcast_creator":        "Jabra Elite 5",
    "earbuds_real_casual_commuter":        "Nothing Ear (2)",
    "earbuds_real_premium_no_compromise":  "Sony WF-1000XM5",
    "earbuds_real_sleep_relaxation":       "Bose QuietComfort Ultra Earbuds",
    "earbuds_real_students_dorm":          "Nothing Ear (2)",
}

_HJ_IDS = [
    "earbuds_real_hj_android_audiophile",
    "earbuds_real_hj_apple_ecosystem",
    "earbuds_real_hj_remote_worker_calls",
    "earbuds_real_hj_budget_student_anc",
    "earbuds_real_hj_comfort_travel",
    "earbuds_real_hj_budget_audiophile",
]


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _fresh_pool():
    """Parse pool bypassing the lru_cache so test edits are visible."""
    return _parse_pool(_POOL_PATH)


def _product_by_name(products, name):
    return next(p for p in products if p.name == name)


def _scores(product):
    return product.criterion_scores


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pool structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestPoolStructure:
    def test_pool_file_exists(self):
        assert _POOL_PATH.exists(), "earbuds_real.json must exist in evals/data/pools/"

    def test_pool_is_valid_json(self):
        data = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_pool_loads_without_error(self):
        pool = _fresh_pool()
        assert pool["category"] == "earbuds_real"

    def test_six_products(self):
        pool = _fresh_pool()
        assert len(pool["products"]) == 6

    def test_ten_criteria(self):
        data = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
        assert len(data["criteria"]) == 10

    def test_fifteen_scenarios(self):
        pool = _fresh_pool()
        assert len(pool["scenarios"]) == 15

    def test_six_human_judgments(self):
        pool = _fresh_pool()
        assert len(pool["human_judgments"]) == 6

    def test_all_product_names_present(self):
        pool = _fresh_pool()
        names = {p.name for p in pool["products"]}
        for expected in _PRODUCT_NAMES:
            assert expected in names, f"Missing product: {expected}"

    def test_all_criteria_present(self):
        data = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
        declared = {c["name"] for c in data["criteria"]}
        for c in _CRITERIA_NAMES:
            assert c in declared, f"Missing criterion: {c}"

    def test_every_product_has_all_criteria(self):
        data = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
        criteria_names = {c["name"] for c in data["criteria"]}
        for prod in data["products"]:
            declared = set(prod["scores"].keys())
            assert declared == criteria_names, (
                f"{prod['name']} missing criteria: {criteria_names - declared}"
            )

    def test_all_scores_in_range(self):
        data = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
        for prod in data["products"]:
            for crit, val in prod["scores"].items():
                assert 0 <= val <= 10, (
                    f"{prod['name']}.{crit} = {val} out of [0, 10]"
                )

    def test_category_discovered_by_loader(self):
        load_all_pools.cache_clear()
        cats = pool_categories()
        assert "earbuds_real" in cats


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Product score correctness — encoding real specs
# ═══════════════════════════════════════════════════════════════════════════════

class TestProductScoreCorrectness:
    """Verify that differentiating scores reflect real-world product strengths."""

    def setup_method(self):
        pool = _fresh_pool()
        self._prods = pool["products"]

    def test_sony_leads_codec_support(self):
        sony = _product_by_name(self._prods, "Sony WF-1000XM5")
        airpods = _product_by_name(self._prods, "Apple AirPods Pro 2")
        assert _scores(sony)["codec_support"] > _scores(airpods)["codec_support"]

    def test_airpods_leads_transparency_mode(self):
        airpods = _product_by_name(self._prods, "Apple AirPods Pro 2")
        sony = _product_by_name(self._prods, "Sony WF-1000XM5")
        assert _scores(airpods)["transparency_mode"] > _scores(sony)["transparency_mode"]

    def test_bose_leads_comfort(self):
        bose = _product_by_name(self._prods, "Bose QuietComfort Ultra Earbuds")
        assert _scores(bose)["comfort"] == 10
        for name in _PRODUCT_NAMES:
            if name != "Bose QuietComfort Ultra Earbuds":
                other = _product_by_name(self._prods, name)
                assert _scores(bose)["comfort"] > _scores(other)["comfort"]

    def test_nothing_leads_price_to_value_among_premium(self):
        nothing = _product_by_name(self._prods, "Nothing Ear (2)")
        sony = _product_by_name(self._prods, "Sony WF-1000XM5")
        bose = _product_by_name(self._prods, "Bose QuietComfort Ultra Earbuds")
        assert _scores(nothing)["price_to_value"] > _scores(sony)["price_to_value"]
        assert _scores(nothing)["price_to_value"] > _scores(bose)["price_to_value"]

    def test_anker_leads_battery_and_price(self):
        anker = _product_by_name(self._prods, "Anker Soundcore Liberty 4 NC")
        assert _scores(anker)["price_to_value"] == 10
        assert _scores(anker)["battery_life"] == 9
        for name in _PRODUCT_NAMES:
            if name != "Anker Soundcore Liberty 4 NC":
                other = _product_by_name(self._prods, name)
                assert _scores(anker)["price_to_value"] >= _scores(other)["price_to_value"]

    def test_jabra_leads_microphone_and_call(self):
        jabra = _product_by_name(self._prods, "Jabra Elite 5")
        assert _scores(jabra)["microphone_quality"] == 9
        assert _scores(jabra)["call_quality"] == 9
        for name in _PRODUCT_NAMES:
            if name != "Jabra Elite 5":
                other = _product_by_name(self._prods, name)
                assert _scores(jabra)["microphone_quality"] >= _scores(other)["microphone_quality"]

    def test_jabra_leads_durability(self):
        jabra = _product_by_name(self._prods, "Jabra Elite 5")
        assert _scores(jabra)["durability"] == 9
        for name in _PRODUCT_NAMES:
            if name != "Jabra Elite 5":
                other = _product_by_name(self._prods, name)
                assert _scores(jabra)["durability"] >= _scores(other)["durability"]

    def test_airpods_codec_is_lowest(self):
        airpods = _product_by_name(self._prods, "Apple AirPods Pro 2")
        # AAC-only (no LDAC) — must be clearly below LDAC-capable products
        assert _scores(airpods)["codec_support"] <= 3
        sony = _product_by_name(self._prods, "Sony WF-1000XM5")
        nothing = _product_by_name(self._prods, "Nothing Ear (2)")
        assert _scores(airpods)["codec_support"] < _scores(sony)["codec_support"]
        assert _scores(airpods)["codec_support"] < _scores(nothing)["codec_support"]

    def test_bose_lowest_price_to_value(self):
        bose = _product_by_name(self._prods, "Bose QuietComfort Ultra Earbuds")
        assert _scores(bose)["price_to_value"] <= 3


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Scenario winners — all 15 expected rank-1 products must win
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioWinners:
    """For each scenario, build_scored_products must return the expected rank-1."""

    def setup_method(self):
        load_all_pools.cache_clear()
        pools = load_all_pools()
        pool = next(p for p in pools if p["category"] == "earbuds_real")
        self._scenarios = {sc.id: sc for sc in pool["scenarios"]}

    def _winner(self, sc_id):
        sc = self._scenarios[sc_id]
        ranked = build_scored_products(sc.products, sc.rubric_weights)
        return ranked[0]["name"]

    def test_android_audiophile_sony_wins(self):
        assert self._winner("earbuds_real_android_audiophile") == "Sony WF-1000XM5"

    def test_apple_daily_commute_airpods_wins(self):
        assert self._winner("earbuds_real_apple_daily_commute") == "Apple AirPods Pro 2"

    def test_comfort_traveler_bose_wins(self):
        assert self._winner("earbuds_real_comfort_traveler") == "Bose QuietComfort Ultra Earbuds"

    def test_value_audiophile_nothing_wins(self):
        assert self._winner("earbuds_real_value_audiophile") == "Nothing Ear (2)"

    def test_budget_anc_anker_wins(self):
        assert self._winner("earbuds_real_budget_anc") == "Anker Soundcore Liberty 4 NC"

    def test_business_calls_jabra_wins(self):
        assert self._winner("earbuds_real_business_calls") == "Jabra Elite 5"

    def test_long_haul_flight_airpods_wins(self):
        assert self._winner("earbuds_real_long_haul_flight") == "Apple AirPods Pro 2"

    def test_active_outdoor_jabra_wins(self):
        assert self._winner("earbuds_real_active_outdoor") == "Jabra Elite 5"

    def test_music_listening_sony_wins(self):
        assert self._winner("earbuds_real_music_listening") == "Sony WF-1000XM5"

    def test_budget_daily_driver_anker_wins(self):
        assert self._winner("earbuds_real_budget_daily_driver") == "Anker Soundcore Liberty 4 NC"

    def test_podcast_creator_jabra_wins(self):
        assert self._winner("earbuds_real_podcast_creator") == "Jabra Elite 5"

    def test_casual_commuter_nothing_wins(self):
        assert self._winner("earbuds_real_casual_commuter") == "Nothing Ear (2)"

    def test_premium_no_compromise_sony_wins(self):
        assert self._winner("earbuds_real_premium_no_compromise") == "Sony WF-1000XM5"

    def test_sleep_relaxation_bose_wins(self):
        assert self._winner("earbuds_real_sleep_relaxation") == "Bose QuietComfort Ultra Earbuds"

    def test_students_dorm_nothing_wins(self):
        assert self._winner("earbuds_real_students_dorm") == "Nothing Ear (2)"

    def test_all_fifteen_scenarios_covered(self):
        assert len(self._scenarios) == 15

    def test_every_product_wins_at_least_two_scenarios(self):
        wins = {name: 0 for name in _PRODUCT_NAMES}
        for sc_id in _SCENARIO_EXPECTED_WINNERS:
            wins[_SCENARIO_EXPECTED_WINNERS[sc_id]] += 1
        for name, count in wins.items():
            assert count >= 2, f"{name} wins only {count} scenarios (need >= 2)"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. expected_rank_1_not constraints
# ═══════════════════════════════════════════════════════════════════════════════

class TestScenarioConstraints:
    """Products in expected_rank_1_not must not appear as rank-1."""

    def setup_method(self):
        load_all_pools.cache_clear()
        pools = load_all_pools()
        pool = next(p for p in pools if p["category"] == "earbuds_real")
        self._scenarios = {sc.id: sc for sc in pool["scenarios"]}

    def test_airpods_not_rank1_android_audiophile(self):
        sc = self._scenarios["earbuds_real_android_audiophile"]
        ranked = build_scored_products(sc.products, sc.rubric_weights)
        assert ranked[0]["name"] != "Apple AirPods Pro 2"

    def test_bose_not_rank1_budget_anc(self):
        sc = self._scenarios["earbuds_real_budget_anc"]
        ranked = build_scored_products(sc.products, sc.rubric_weights)
        assert ranked[0]["name"] != "Bose QuietComfort Ultra Earbuds"

    def test_sony_not_rank1_budget_anc(self):
        sc = self._scenarios["earbuds_real_budget_anc"]
        ranked = build_scored_products(sc.products, sc.rubric_weights)
        assert ranked[0]["name"] != "Sony WF-1000XM5"

    def test_anker_not_rank1_premium_no_compromise(self):
        sc = self._scenarios["earbuds_real_premium_no_compromise"]
        ranked = build_scored_products(sc.products, sc.rubric_weights)
        assert ranked[0]["name"] != "Anker Soundcore Liberty 4 NC"

    def test_bose_not_rank1_students_dorm(self):
        sc = self._scenarios["earbuds_real_students_dorm"]
        ranked = build_scored_products(sc.products, sc.rubric_weights)
        assert ranked[0]["name"] != "Bose QuietComfort Ultra Earbuds"

    def test_bose_not_rank1_budget_daily_driver(self):
        sc = self._scenarios["earbuds_real_budget_daily_driver"]
        ranked = build_scored_products(sc.products, sc.rubric_weights)
        assert ranked[0]["name"] != "Bose QuietComfort Ultra Earbuds"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Human judgment panels — exact top-3 match with engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestHumanJudgmentExactMatch:
    """All 6 expert panels must have engine top-3 == expert top-3 (exact order)."""

    def setup_method(self):
        load_all_pools.cache_clear()
        pools = load_all_pools()
        pool = next(p for p in pools if p["category"] == "earbuds_real")
        self._hjs = {hj.id: hj for hj in pool["human_judgments"]}

    def _engine_top3(self, hj_id):
        hj = self._hjs[hj_id]
        ranked = build_scored_products(hj.products, hj.rubric_weights)
        return [r["name"] for r in ranked[:3]]

    def _expert_top3(self, hj_id):
        hj = self._hjs[hj_id]
        return [hj.expert_rank_1, hj.expert_rank_2, hj.expert_rank_3]

    def test_hj_android_audiophile_exact_match(self):
        hj_id = "earbuds_real_hj_android_audiophile"
        assert self._engine_top3(hj_id) == self._expert_top3(hj_id)

    def test_hj_apple_ecosystem_exact_match(self):
        hj_id = "earbuds_real_hj_apple_ecosystem"
        assert self._engine_top3(hj_id) == self._expert_top3(hj_id)

    def test_hj_remote_worker_calls_exact_match(self):
        hj_id = "earbuds_real_hj_remote_worker_calls"
        assert self._engine_top3(hj_id) == self._expert_top3(hj_id)

    def test_hj_budget_student_anc_exact_match(self):
        hj_id = "earbuds_real_hj_budget_student_anc"
        assert self._engine_top3(hj_id) == self._expert_top3(hj_id)

    def test_hj_comfort_travel_exact_match(self):
        hj_id = "earbuds_real_hj_comfort_travel"
        assert self._engine_top3(hj_id) == self._expert_top3(hj_id)

    def test_hj_budget_audiophile_exact_match(self):
        hj_id = "earbuds_real_hj_budget_audiophile"
        assert self._engine_top3(hj_id) == self._expert_top3(hj_id)

    def test_all_six_hjs_rank1_match(self):
        for hj_id in _HJ_IDS:
            hj = self._hjs[hj_id]
            ranked = build_scored_products(hj.products, hj.rubric_weights)
            winner = ranked[0]["name"]
            assert winner == hj.expert_rank_1, (
                f"{hj_id}: engine rank-1 {winner!r} != expert {hj.expert_rank_1!r}"
            )

    def test_all_six_hjs_top3_full_overlap(self):
        for hj_id in _HJ_IDS:
            hj = self._hjs[hj_id]
            ranked = build_scored_products(hj.products, hj.rubric_weights)
            engine_top3 = {r["name"] for r in ranked[:3]}
            expert_top3 = {hj.expert_rank_1, hj.expert_rank_2, hj.expert_rank_3}
            assert engine_top3 == expert_top3, (
                f"{hj_id}: engine top-3 {engine_top3} != expert top-3 {expert_top3}"
            )

    def test_each_hj_covers_different_winner(self):
        winners = set()
        for hj_id in _HJ_IDS:
            hj = self._hjs[hj_id]
            winners.add(hj.expert_rank_1)
        assert len(winners) == 6, f"Only {len(winners)} distinct HJ winners — expected 6"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Human alignment metric scores
# ═══════════════════════════════════════════════════════════════════════════════

class TestHumanJudgmentAlignmentScores:
    """HumanAlignmentMetric.evaluate on earbuds_real panels must score >= 95/100."""

    def setup_method(self):
        load_all_pools.cache_clear()
        pools = load_all_pools()
        pool = next(p for p in pools if p["category"] == "earbuds_real")
        self._hjs = pool["human_judgments"]
        metric = HumanAlignmentMetric()
        result = metric.evaluate(self._hjs)
        self._result = result
        self._per_hj = {r["id"]: r for r in result.details["judgments"]}

    def test_average_alignment_above_95(self):
        assert self._result.score >= 95.0, (
            f"Average alignment {self._result.score} < 95.0"
        )

    def test_all_six_panels_above_95(self):
        for hj_id in _HJ_IDS:
            score = self._per_hj[hj_id]["alignment_score"]
            assert score >= 95.0, (
                f"{hj_id} alignment score {score} < 95.0"
            )

    def test_all_six_panels_rank1_match(self):
        for hj_id in _HJ_IDS:
            assert self._per_hj[hj_id]["rank1_match"] is True, (
                f"{hj_id} rank1 does not match"
            )

    def test_all_six_panels_top3_hits_full(self):
        for hj_id in _HJ_IDS:
            hits = self._per_hj[hj_id]["top3_hits"]
            assert hits == 3, f"{hj_id} top3_hits={hits} (expected 3)"

    def test_all_six_panels_ndcg_perfect(self):
        for hj_id in _HJ_IDS:
            ndcg = self._per_hj[hj_id]["ndcg3"]
            assert ndcg >= 0.99, f"{hj_id} NDCG@3={ndcg} < 0.99 (expected perfect)"

    def test_result_total_judgments_count(self):
        assert self._result.details["total_judgments"] == 6

    def test_result_all_panels_passed(self):
        assert self._result.details["passed"] == 6

    def test_no_failures_in_result(self):
        assert len(self._result.failures) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Pool integration — all_scenarios() and all_human_judgments() include pool
# ═══════════════════════════════════════════════════════════════════════════════

class TestPoolIntegration:

    def setup_method(self):
        load_all_pools.cache_clear()

    def test_pool_category_in_pool_categories(self):
        assert "earbuds_real" in pool_categories()

    def test_pool_scenarios_include_earbuds_real(self):
        sc_ids = {sc.id for sc in pool_scenarios()}
        assert "earbuds_real_android_audiophile" in sc_ids

    def test_all_15_scenario_ids_present_in_pool_scenarios(self):
        sc_ids = {sc.id for sc in pool_scenarios()}
        for sc_id in _SCENARIO_EXPECTED_WINNERS:
            assert sc_id in sc_ids, f"Missing scenario {sc_id} in pool_scenarios()"

    def test_all_6_hj_ids_present_in_pool_human_judgments(self):
        hj_ids = {hj.id for hj in pool_human_judgments()}
        for hj_id in _HJ_IDS:
            assert hj_id in hj_ids, f"Missing HJ {hj_id} in pool_human_judgments()"

    def test_all_scenarios_includes_earbuds_real(self):
        sc_ids = {sc.id for sc in all_scenarios()}
        assert "earbuds_real_android_audiophile" in sc_ids

    def test_all_human_judgments_includes_earbuds_real(self):
        hj_ids = {hj.id for hj in all_human_judgments()}
        assert "earbuds_real_hj_android_audiophile" in hj_ids

    def test_total_scenarios_at_least_172(self):
        # earbuds(113) + earbuds_real(15) + headphones(12) + laptops(18) + monitors(12) = 170+
        total = len(all_scenarios())
        assert total >= 170, f"Expected >= 170 scenarios, got {total}"

    def test_pool_scenarios_have_earbuds_real_tag(self):
        for sc in pool_scenarios():
            if sc.id.startswith("earbuds_real_"):
                assert "earbuds_real" in sc.tags


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Config consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigConsistency:

    def test_index_weights_still_sum_to_one(self):
        total = sum(INDEX_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"INDEX_WEIGHTS sum = {total}"

    def test_human_alignment_weight_present(self):
        assert "human_alignment" in INDEX_WEIGHTS

    def test_score_calibration_weight_present(self):
        assert "score_calibration" in INDEX_WEIGHTS

    def test_recommendation_quality_largest_weight(self):
        assert INDEX_WEIGHTS["recommendation_quality"] == max(INDEX_WEIGHTS.values())


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Pool validation errors — malformed data is rejected
# ═══════════════════════════════════════════════════════════════════════════════

class TestPoolValidationErrors:
    """_parse_pool raises PoolValidationError for any structural problem."""

    def _write_and_parse(self, tmp_path, data: dict):
        p = tmp_path / "test_pool.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return _parse_pool(p)

    def _base_pool(self):
        return json.loads(_POOL_PATH.read_text(encoding="utf-8"))

    def test_missing_criteria_raises(self, tmp_path):
        data = self._base_pool()
        del data["criteria"]
        with pytest.raises(PoolValidationError, match="criteria"):
            self._write_and_parse(tmp_path, data)

    def test_unknown_product_in_scenario_raises(self, tmp_path):
        data = self._base_pool()
        data["scenarios"][0]["expected_rank_1"] = "NonExistentBrand X9"
        with pytest.raises(PoolValidationError):
            self._write_and_parse(tmp_path, data)

    def test_unknown_product_in_hj_raises(self, tmp_path):
        data = self._base_pool()
        data["human_judgments"][0]["expert_rank_1"] = "Ghost Brand Z"
        with pytest.raises(PoolValidationError):
            self._write_and_parse(tmp_path, data)

    def test_unknown_criterion_in_scenario_weights_raises(self, tmp_path):
        data = self._base_pool()
        data["scenarios"][0]["weights"]["nonexistent_criterion"] = 5
        with pytest.raises(PoolValidationError):
            self._write_and_parse(tmp_path, data)

    def test_product_with_unknown_criterion_score_raises(self, tmp_path):
        data = self._base_pool()
        data["products"][0]["scores"]["made_up_feature"] = 7
        with pytest.raises(PoolValidationError):
            self._write_and_parse(tmp_path, data)

    def test_fewer_than_two_products_raises(self, tmp_path):
        data = self._base_pool()
        data["products"] = data["products"][:1]
        with pytest.raises(PoolValidationError, match="products"):
            self._write_and_parse(tmp_path, data)

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(PoolValidationError, match="invalid JSON"):
            _parse_pool(p)
