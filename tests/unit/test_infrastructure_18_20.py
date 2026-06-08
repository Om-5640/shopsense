"""
Tests for Fixes 18, 19, 20:

Fix 18 — Extraction Recall:
  TestExtractionScenarios       — scenario dataclass construction
  TestExtractionRecallMetric    — metric evaluate() with real normalize_analysis
  TestExtractionRecallEdgeCases — empty corpus, vacuous recall, precision checks

Fix 19 — Ranking Stability:
  TestSpearmanCorrelation       — pure-Python Spearman impl correctness
  TestRubricPerturbation        — noise application + renormalisation
  TestRankingStabilityMetric    — full metric evaluate() with stability scenarios
  TestStabilityScenarios        — scenario dataclass construction

Fix 20 — Redis Cache Tier:
  TestCacheFileOnly             — get/set/purge without Redis (existing behaviour)
  TestCacheRedisPath            — Redis read/write paths with mocked client
  TestCacheRedisGracefulDegradation — Redis errors fall through to file
  TestCacheBackendDetection     — cache_backend() returns correct string
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup so imports resolve from project root ───────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Capture real cache functions BEFORE any other test module can replace them ──
# test_quality_gaps_13_17.py does sys.modules["cache"].get = lambda ... at module
# level, which corrupts cache.get for all subsequent tests.  Saving references
# here (alphabetically earlier) preserves the real implementations.
import cache as _real_cache_mod
_REAL_CACHE_GET = _real_cache_mod.get
_REAL_CACHE_SET = _real_cache_mod.set
_REAL_CACHE_FILE_GET = _real_cache_mod._file_get
_REAL_CACHE_FILE_SET = _real_cache_mod._file_set


# =============================================================================
# Fix 18: Extraction Recall
# =============================================================================

class TestExtractionScenarios:
    """Verify the scenario dataclass is well-formed."""

    def test_all_scenarios_loadable(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        scenarios = all_extraction_scenarios()
        assert len(scenarios) >= 5

    def test_each_scenario_has_required_fields(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        for sc in all_extraction_scenarios():
            assert sc.id, f"Scenario missing id: {sc}"
            assert sc.description, f"Scenario {sc.id} missing description"
            assert isinstance(sc.analysis_json, dict), f"Scenario {sc.id} analysis_json must be dict"
            assert isinstance(sc.expected_products, list), f"Scenario {sc.id} expected_products must be list"
            assert 0.0 <= sc.min_recall <= 1.0, f"Scenario {sc.id} min_recall out of range"

    def test_scenario_ids_are_unique(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        ids = [sc.id for sc in all_extraction_scenarios()]
        assert len(ids) == len(set(ids)), "Duplicate scenario IDs found"

    def test_empty_scenario_has_no_expected(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        sc = next(s for s in all_extraction_scenarios() if s.id == "ext-005")
        assert sc.expected_products == []
        assert sc.analysis_json["products"] == []

    def test_earbuds_scenario_has_five_products(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        sc = next(s for s in all_extraction_scenarios() if s.id == "ext-001")
        assert len(sc.expected_products) == 5
        assert len(sc.analysis_json["products"]) == 5

    def test_laptop_scenario_keeps_similar_names_distinct(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        sc = next(s for s in all_extraction_scenarios() if s.id == "ext-002")
        names = [p.lower() for p in sc.expected_products]
        assert "acer aspire 5" in names
        assert "acer aspire 3" in names
        assert len(names) == len(set(names))  # no duplicates in expected list


class TestExtractionRecallMetric:
    """Full metric evaluate() using real normalize_analysis."""

    def test_earbuds_scenario_perfect_recall(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        scenarios = [s for s in all_extraction_scenarios() if s.id == "ext-001"]
        result = ExtractionRecallMetric().evaluate(scenarios)
        if result.skipped:
            pytest.skip("analysis_normalizer not importable in this environment")
        assert result.details["scenario_details"][0]["recall"] == pytest.approx(1.0)
        assert result.details["scenario_details"][0]["f1_score"] == pytest.approx(100.0, abs=1)

    def test_laptop_dedup_keeps_distinct_models(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        scenarios = [s for s in all_extraction_scenarios() if s.id == "ext-002"]
        result = ExtractionRecallMetric().evaluate(scenarios)
        if result.skipped:
            pytest.skip("analysis_normalizer not importable in this environment")
        detail = result.details["scenario_details"][0]
        # "acer aspire 5" and "acer aspire 3" must both survive — no false dedup
        assert detail["recall"] == pytest.approx(1.0), f"missing: {detail['missing']}"

    def test_noisy_llm_output_survives(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        scenarios = [s for s in all_extraction_scenarios() if s.id == "ext-003"]
        result = ExtractionRecallMetric().evaluate(scenarios)
        if result.skipped:
            pytest.skip("analysis_normalizer not importable in this environment")
        detail = result.details["scenario_details"][0]
        assert detail["recall"] == pytest.approx(1.0), f"missing: {detail['missing']}"

    def test_empty_corpus_vacuously_perfect(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        scenarios = [s for s in all_extraction_scenarios() if s.id == "ext-005"]
        result = ExtractionRecallMetric().evaluate(scenarios)
        if result.skipped:
            pytest.skip("analysis_normalizer not importable in this environment")
        assert result.score == pytest.approx(100.0)

    def test_no_unexpected_products_hallucinated(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        scenarios = [s for s in all_extraction_scenarios() if s.unexpected_products]
        result = ExtractionRecallMetric().evaluate(scenarios)
        if result.skipped:
            pytest.skip("analysis_normalizer not importable in this environment")
        for detail in result.details["scenario_details"]:
            assert detail["hallucinated"] == [], (
                f"Hallucinated unexpected products in {detail['id']}: {detail['hallucinated']}"
            )

    def test_full_suite_passes_threshold(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        from evals.config import PASS_THRESHOLDS
        result = ExtractionRecallMetric().evaluate(all_extraction_scenarios())
        if result.skipped:
            pytest.skip("analysis_normalizer not importable in this environment")
        assert result.score >= PASS_THRESHOLDS.get("extraction_recall", 90.0) - 5.0, (
            f"Extraction recall score {result.score} well below threshold — "
            f"failures: {result.failures[:3]}"
        )

    def test_metric_skips_when_no_scenarios(self):
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        result = ExtractionRecallMetric().evaluate([])
        assert result.skipped is True

    def test_metric_result_has_expected_detail_keys(self):
        from evals.benchmarks.extraction_recall import all_extraction_scenarios
        from evals.metrics.extraction_recall import ExtractionRecallMetric
        result = ExtractionRecallMetric().evaluate(all_extraction_scenarios())
        if result.skipped:
            pytest.skip("analysis_normalizer not importable in this environment")
        assert "total_scenarios" in result.details
        assert "avg_recall" in result.details
        assert "avg_precision" in result.details
        assert "scenario_details" in result.details


class TestExtractionRecallEdgeCases:
    """Edge cases: manual fixture injection (does not need full normalizer)."""

    def _build_metric_with_mock_normalize(self, mock_result: dict):
        """Patch normalize_analysis inside the metric module."""
        import evals.metrics.extraction_recall as er_mod
        original = er_mod._normalize
        er_mod._normalize = lambda raw: mock_result
        er_mod._HAS_NORMALIZER = True
        return er_mod, original

    def test_perfect_recall_when_all_expected_found(self):
        import evals.metrics.extraction_recall as er_mod
        from evals.benchmarks.extraction_recall import ExtractionScenario
        orig = er_mod._normalize
        orig_flag = er_mod._HAS_NORMALIZER
        try:
            er_mod._normalize = lambda raw: {
                "products": [{"name": "Sony WF-C500"}, {"name": "Boat Airdopes 141"}],
                "summary": "", "materials": [],
            }
            er_mod._HAS_NORMALIZER = True
            sc = ExtractionScenario(
                id="t-001", description="test", category="test",
                analysis_json={"products": [], "summary": "", "materials": []},
                expected_products=["sony wf-c500", "boat airdopes 141"],
            )
            result = er_mod.ExtractionRecallMetric().evaluate([sc])
            assert result.details["scenario_details"][0]["recall"] == pytest.approx(1.0)
        finally:
            er_mod._normalize = orig
            er_mod._HAS_NORMALIZER = orig_flag

    def test_zero_recall_when_nothing_found(self):
        import evals.metrics.extraction_recall as er_mod
        from evals.benchmarks.extraction_recall import ExtractionScenario
        orig = er_mod._normalize
        orig_flag = er_mod._HAS_NORMALIZER
        try:
            er_mod._normalize = lambda raw: {"products": [], "summary": "", "materials": []}
            er_mod._HAS_NORMALIZER = True
            sc = ExtractionScenario(
                id="t-002", description="test", category="test",
                analysis_json={"products": [], "summary": "", "materials": []},
                expected_products=["sony wf-c500", "boat airdopes 141"],
            )
            result = er_mod.ExtractionRecallMetric().evaluate([sc])
            assert result.details["scenario_details"][0]["recall"] == pytest.approx(0.0)
            assert result.score == pytest.approx(0.0)
        finally:
            er_mod._normalize = orig
            er_mod._HAS_NORMALIZER = orig_flag

    def test_precision_penalises_over_extraction(self):
        import evals.metrics.extraction_recall as er_mod
        from evals.benchmarks.extraction_recall import ExtractionScenario
        orig = er_mod._normalize
        orig_flag = er_mod._HAS_NORMALIZER
        try:
            # 1 expected found + 9 extras → precision = 1/10 = 0.1
            er_mod._normalize = lambda raw: {
                "products": [{"name": f"Product {i}"} for i in range(10)],
                "summary": "", "materials": [],
            }
            er_mod._HAS_NORMALIZER = True
            sc = ExtractionScenario(
                id="t-003", description="test", category="test",
                analysis_json={"products": [], "summary": "", "materials": []},
                expected_products=["product 0"],
            )
            result = er_mod.ExtractionRecallMetric().evaluate([sc])
            detail = result.details["scenario_details"][0]
            assert detail["precision"] == pytest.approx(0.1, abs=0.01)
            assert detail["recall"] == pytest.approx(1.0)
            # F1 = 2 * 1.0 * 0.1 / 1.1 ≈ 0.182
            assert detail["f1"] == pytest.approx(2 * 1.0 * 0.1 / 1.1, abs=0.01)
        finally:
            er_mod._normalize = orig
            er_mod._HAS_NORMALIZER = orig_flag


# =============================================================================
# Fix 19: Ranking Stability
# =============================================================================

class TestSpearmanCorrelation:
    """Unit tests for the _spearman() helper."""

    def _spearman(self, r1, r2):
        from evals.metrics.ranking_stability import _spearman
        return _spearman(r1, r2)

    def test_identical_rankings_rho_one(self):
        assert self._spearman(["A", "B", "C"], ["A", "B", "C"]) == pytest.approx(1.0)

    def test_reversed_rankings_rho_negative_one(self):
        # Perfect inversion: 4 items
        rho = self._spearman(["A", "B", "C", "D"], ["D", "C", "B", "A"])
        assert rho == pytest.approx(-1.0, abs=0.01)

    def test_single_item_returns_one(self):
        assert self._spearman(["A"], ["A"]) == pytest.approx(1.0)

    def test_empty_list_returns_one(self):
        assert self._spearman([], []) == pytest.approx(1.0)

    def test_two_items_swapped_rho_negative_one(self):
        rho = self._spearman(["A", "B"], ["B", "A"])
        assert rho == pytest.approx(-1.0, abs=0.01)

    def test_disjoint_rankings_uses_common_subset(self):
        # r1 has A,B,C; r2 has only A,B → common = [A, B]
        # both agree → rho = 1.0
        rho = self._spearman(["A", "B", "C"], ["A", "B"])
        assert rho == pytest.approx(1.0)

    def test_partial_swap(self):
        # A=1st in both, C moves from 3rd to 2nd, B from 2nd to 3rd
        rho = self._spearman(["A", "B", "C"], ["A", "C", "B"])
        # d²: A→0, B→1, C→1  ==> rho = 1 - 6*2/(3*8) = 1 - 0.5 = 0.5
        assert rho == pytest.approx(0.5, abs=0.01)


class TestRubricPerturbation:
    """Unit tests for _perturb_rubric()."""

    def test_total_weight_preserved(self):
        from evals.metrics.ranking_stability import _perturb_rubric
        import random
        from evals.benchmarks.base import RubricWeight
        rubric = [
            RubricWeight("a", "A", 4.0),
            RubricWeight("b", "B", 3.0),
            RubricWeight("c", "C", 2.0),
            RubricWeight("d", "D", 1.0),
        ]
        rng = random.Random(42)
        original_total = sum(r.weight for r in rubric)
        for _ in range(20):
            perturbed = _perturb_rubric(rubric, rng)
            new_total = sum(r.weight for r in perturbed)
            assert abs(new_total - original_total) < 1e-4, (
                f"Total weight changed: {original_total} → {new_total}"
            )

    def test_all_weights_positive(self):
        from evals.metrics.ranking_stability import _perturb_rubric
        import random
        from evals.benchmarks.base import RubricWeight
        rubric = [RubricWeight("a", "A", 0.01)]  # very small weight — test floor
        rng = random.Random(7)
        for _ in range(50):
            perturbed = _perturb_rubric(rubric, rng)
            for r in perturbed:
                assert r.weight > 0, f"Weight went non-positive: {r.weight}"

    def test_criteria_names_preserved(self):
        from evals.metrics.ranking_stability import _perturb_rubric
        import random
        from evals.benchmarks.base import RubricWeight
        rubric = [RubricWeight("x", "X", 5.0), RubricWeight("y", "Y", 5.0)]
        rng = random.Random(1)
        perturbed = _perturb_rubric(rubric, rng)
        assert [r.criterion for r in perturbed] == ["x", "y"]

    def test_perturbation_is_non_trivial(self):
        from evals.metrics.ranking_stability import _perturb_rubric
        import random
        from evals.benchmarks.base import RubricWeight
        rubric = [RubricWeight("a", "A", 4.0), RubricWeight("b", "B", 4.0)]
        rng = random.Random(99)
        # Over many perturbations, at least one should differ from base
        changed = False
        for _ in range(20):
            p = _perturb_rubric(rubric, rng)
            if any(abs(p[i].weight - rubric[i].weight) > 0.001 for i in range(len(rubric))):
                changed = True
                break
        assert changed, "Perturbation never moved any weight"


class TestStabilityScenarios:
    """Verify stability scenario dataclasses."""

    def test_all_scenarios_loadable(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        scenarios = all_stability_scenarios()
        assert len(scenarios) >= 4

    def test_each_scenario_has_products(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        for sc in all_stability_scenarios():
            assert len(sc.products) >= 2, f"Scenario {sc.id} needs ≥2 products"
            assert len(sc.base_rubric) >= 1, f"Scenario {sc.id} needs ≥1 criterion"

    def test_single_criterion_scenario_present(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        sc = next(s for s in all_stability_scenarios() if s.id == "sc-004")
        assert len(sc.base_rubric) == 1
        assert sc.min_spearman == pytest.approx(1.0)


class TestRankingStabilityMetric:
    """Full metric evaluate() tests."""

    def test_single_criterion_perfectly_stable(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        from evals.metrics.ranking_stability import RankingStabilityMetric
        scenarios = [s for s in all_stability_scenarios() if s.id == "sc-004"]
        result = RankingStabilityMetric().evaluate(scenarios)
        # Single-criterion ranking can never change → spearman always 1.0
        assert result.score == pytest.approx(100.0, abs=0.1)
        assert result.passed

    def test_clear_winner_scenario_high_stability(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        from evals.metrics.ranking_stability import RankingStabilityMetric
        scenarios = [s for s in all_stability_scenarios() if s.id == "sc-001"]
        result = RankingStabilityMetric().evaluate(scenarios)
        # sc-001 has a 3-pt+ leader — should be very stable
        assert result.score >= 80.0, f"Expected high stability, got {result.score}"

    def test_tight_cluster_may_be_less_stable(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        from evals.metrics.ranking_stability import RankingStabilityMetric
        scenarios = [s for s in all_stability_scenarios() if s.id == "sc-002"]
        result = RankingStabilityMetric().evaluate(scenarios)
        # Tight cluster may fluctuate — metric should not crash and score is a float
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 100.0

    def test_full_suite_overall_passes_ci_threshold(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        from evals.metrics.ranking_stability import RankingStabilityMetric
        from evals.config import CI_BLOCK_THRESHOLDS
        result = RankingStabilityMetric().evaluate(all_stability_scenarios())
        threshold = CI_BLOCK_THRESHOLDS.get("ranking_stability", 65.0)
        assert result.score >= threshold, (
            f"Ranking stability {result.score:.1f} below CI threshold {threshold} — "
            f"failures: {result.failures}"
        )

    def test_empty_scenarios_returns_skip(self):
        from evals.metrics.ranking_stability import RankingStabilityMetric
        result = RankingStabilityMetric().evaluate([])
        assert result.skipped is True

    def test_metric_result_has_perturbation_details(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        from evals.metrics.ranking_stability import RankingStabilityMetric, N_PERTURBATIONS
        scenarios = [all_stability_scenarios()[0]]
        result = RankingStabilityMetric().evaluate(scenarios)
        detail = result.details["scenario_details"][0]
        assert len(detail["perturbations"]) == N_PERTURBATIONS
        assert "mean_spearman" in detail
        assert "rank_1_stable_count" in detail

    def test_deterministic_across_runs(self):
        from evals.benchmarks.ranking_stability import all_stability_scenarios
        from evals.metrics.ranking_stability import RankingStabilityMetric
        scenarios = all_stability_scenarios()
        r1 = RankingStabilityMetric().evaluate(scenarios)
        r2 = RankingStabilityMetric().evaluate(scenarios)
        assert r1.score == pytest.approx(r2.score, abs=0.001), (
            "Metric is not deterministic — check random seed"
        )


# =============================================================================
# Fix 20: Redis Cache Tier
# =============================================================================

class TestCacheFileOnly:
    """File-tier behaviour is unchanged when Redis is not configured."""

    def _fresh_cache(self, tmp_path, monkeypatch):
        """Point cache to temp dir with no Redis, restore real get/set."""
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setenv("REDIS_URL", "")
        monkeypatch.setattr(cache_mod, "_redis_client", None)
        monkeypatch.setattr(cache_mod, "_redis_checked", False)
        # Restore real functions (may have been replaced by other test modules at import time)
        monkeypatch.setattr(cache_mod, "get", _REAL_CACHE_GET)
        monkeypatch.setattr(cache_mod, "set", _REAL_CACHE_SET)
        monkeypatch.setattr(cache_mod, "_file_get", _REAL_CACHE_FILE_GET)
        monkeypatch.setattr(cache_mod, "_file_set", _REAL_CACHE_FILE_SET)
        return cache_mod

    def test_miss_returns_none(self, tmp_path, monkeypatch):
        c = self._fresh_cache(tmp_path, monkeypatch)
        assert c.get("test", "missing_key") is None

    def test_set_then_get_returns_value(self, tmp_path, monkeypatch):
        c = self._fresh_cache(tmp_path, monkeypatch)
        c.set("test", "k1", {"data": 42})
        assert c.get("test", "k1") == {"data": 42}

    def test_set_then_get_list_value(self, tmp_path, monkeypatch):
        c = self._fresh_cache(tmp_path, monkeypatch)
        c.set("items", "k2", [1, 2, 3])
        assert c.get("items", "k2") == [1, 2, 3]

    def test_expired_entry_returns_none(self, tmp_path, monkeypatch):
        c = self._fresh_cache(tmp_path, monkeypatch)
        c.set("test", "k3", "hello")
        # Manually rewrite timestamp to expired
        path = c._cache_path("test", "k3")
        with open(path, "r") as f:
            entry = json.load(f)
        entry["timestamp"] = time.time() - c.CACHE_TTL_SECONDS - 1
        with open(path, "w") as f:
            json.dump(entry, f)
        assert c.get("test", "k3") is None

    def test_corrupt_file_returns_none(self, tmp_path, monkeypatch):
        c = self._fresh_cache(tmp_path, monkeypatch)
        c.set("test", "k4", "data")
        path = c._cache_path("test", "k4")
        path.write_text("NOT JSON")
        assert c.get("test", "k4") is None

    def test_purge_expired_deletes_stale_files(self, tmp_path, monkeypatch):
        c = self._fresh_cache(tmp_path, monkeypatch)
        c.set("test", "k5", "a")
        c.set("test", "k6", "b")
        # Expire k5
        path = c._cache_path("test", "k5")
        with open(path, "r") as f:
            entry = json.load(f)
        entry["timestamp"] = time.time() - c.CACHE_TTL_SECONDS - 1
        with open(path, "w") as f:
            json.dump(entry, f)
        deleted = c.purge_expired()
        assert deleted == 1
        assert c.get("test", "k6") == "b"

    def test_cache_backend_returns_file(self, tmp_path, monkeypatch):
        c = self._fresh_cache(tmp_path, monkeypatch)
        assert c.cache_backend() == "file"


class TestCacheRedisPath:
    """Redis read/write paths with a mocked Redis client."""

    def _setup_redis(self, monkeypatch, store: dict):
        """Inject a mock Redis client that stores in `store`, restore real functions."""
        import cache as cache_mod
        # Restore real get/set so they exercise the Redis path
        monkeypatch.setattr(cache_mod, "get", _REAL_CACHE_GET)
        monkeypatch.setattr(cache_mod, "set", _REAL_CACHE_SET)
        monkeypatch.setattr(cache_mod, "_file_get", _REAL_CACHE_FILE_GET)
        monkeypatch.setattr(cache_mod, "_file_set", _REAL_CACHE_FILE_SET)

        class MockRedis:
            def ping(self): return True
            def get(self, key):
                return store.get(key)
            def setex(self, key, ttl, value):
                store[key] = value

        mock = MockRedis()
        monkeypatch.setattr(cache_mod, "_redis_client", mock)
        monkeypatch.setattr(cache_mod, "_redis_checked", True)
        return mock

    def test_redis_hit_skips_file_read(self, tmp_path, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        store: dict = {}
        rkey = cache_mod._redis_key("pipeline_result", "pk1")
        store[rkey] = json.dumps({"hello": "world"})
        self._setup_redis(monkeypatch, store)

        result = cache_mod.get("pipeline_result", "pk1")
        assert result == {"hello": "world"}

    def test_set_writes_to_both_tiers(self, tmp_path, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        store: dict = {}
        self._setup_redis(monkeypatch, store)

        cache_mod.set("pipeline_result", "pk2", [1, 2, 3])

        # Redis should have it
        rkey = cache_mod._redis_key("pipeline_result", "pk2")
        assert json.loads(store[rkey]) == [1, 2, 3]

        # File should also have it
        path = cache_mod._cache_path("pipeline_result", "pk2")
        assert path.exists()

    def test_redis_miss_falls_through_to_file(self, tmp_path, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        store: dict = {}  # Redis empty
        self._setup_redis(monkeypatch, store)

        # Write only to file
        cache_mod._file_set("pipeline_result", "pk3", {"from": "file"})

        result = cache_mod.get("pipeline_result", "pk3")
        assert result == {"from": "file"}

    def test_pipeline_result_ttl_is_24h(self, tmp_path, monkeypatch):
        import cache as cache_mod
        received_ttl = []

        class CapturingRedis:
            def ping(self): return True
            def get(self, key): return None
            def setex(self, key, ttl, value):
                received_ttl.append(ttl)

        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(cache_mod, "_redis_client", CapturingRedis())
        monkeypatch.setattr(cache_mod, "_redis_checked", True)
        monkeypatch.setattr(cache_mod, "set", _REAL_CACHE_SET)
        monkeypatch.setattr(cache_mod, "_file_set", _REAL_CACHE_FILE_SET)

        cache_mod.set("pipeline_result", "pk4", {})
        assert received_ttl[0] == 86_400  # 24 h

    def test_default_type_ttl_is_7d(self, tmp_path, monkeypatch):
        import cache as cache_mod
        received_ttl = []

        class CapturingRedis:
            def ping(self): return True
            def get(self, key): return None
            def setex(self, key, ttl, value):
                received_ttl.append(ttl)

        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(cache_mod, "_redis_client", CapturingRedis())
        monkeypatch.setattr(cache_mod, "_redis_checked", True)
        monkeypatch.setattr(cache_mod, "set", _REAL_CACHE_SET)
        monkeypatch.setattr(cache_mod, "_file_set", _REAL_CACHE_FILE_SET)

        cache_mod.set("other_type", "pk5", {})
        assert received_ttl[0] == 604_800  # 7 days

    def test_cache_backend_returns_redis(self, tmp_path, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        self._setup_redis(monkeypatch, {})
        assert cache_mod.cache_backend() == "redis"


class TestCacheRedisGracefulDegradation:
    """Redis failures must never surface to the caller."""

    def test_redis_get_exception_falls_through_to_file(self, tmp_path, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(cache_mod, "get", _REAL_CACHE_GET)
        monkeypatch.setattr(cache_mod, "_file_get", _REAL_CACHE_FILE_GET)
        monkeypatch.setattr(cache_mod, "_file_set", _REAL_CACHE_FILE_SET)

        class BrokenRedis:
            def ping(self): return True
            def get(self, key): raise ConnectionError("Redis down")
            def setex(self, *a, **kw): raise ConnectionError("Redis down")

        monkeypatch.setattr(cache_mod, "_redis_client", BrokenRedis())
        monkeypatch.setattr(cache_mod, "_redis_checked", True)

        # Write file-only backup
        _REAL_CACHE_FILE_SET("test", "k_broken", {"from": "file"})

        result = cache_mod.get("test", "k_broken")
        assert result == {"from": "file"}

    def test_redis_set_exception_does_not_raise(self, tmp_path, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(cache_mod, "get", _REAL_CACHE_GET)
        monkeypatch.setattr(cache_mod, "set", _REAL_CACHE_SET)
        monkeypatch.setattr(cache_mod, "_file_get", _REAL_CACHE_FILE_GET)
        monkeypatch.setattr(cache_mod, "_file_set", _REAL_CACHE_FILE_SET)

        class BrokenRedis:
            def ping(self): return True
            def get(self, key): return None
            def setex(self, *a, **kw): raise ConnectionError("Redis down")

        monkeypatch.setattr(cache_mod, "_redis_client", BrokenRedis())
        monkeypatch.setattr(cache_mod, "_redis_checked", True)

        # Must not raise
        cache_mod.set("test", "k_set_broken", {"x": 1})

        # File should still have it
        assert cache_mod.get("test", "k_set_broken") == {"x": 1}

    def test_no_redis_url_returns_none_client(self, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_redis_checked", False)
        monkeypatch.setattr(cache_mod, "_redis_client", None)
        monkeypatch.delenv("REDIS_URL", raising=False)
        client = cache_mod._get_redis()
        assert client is None


class TestCacheBackendDetection:
    """cache_backend() helper correctness."""

    def test_no_redis_url_returns_file(self, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_redis_checked", False)
        monkeypatch.setattr(cache_mod, "_redis_client", None)
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert cache_mod.cache_backend() == "file"

    def test_redis_client_present_returns_redis(self, monkeypatch):
        import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_redis_checked", True)
        monkeypatch.setattr(cache_mod, "_redis_client", MagicMock())
        assert cache_mod.cache_backend() == "redis"
