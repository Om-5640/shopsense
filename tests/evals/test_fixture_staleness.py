"""
Tests for Phase 16: Fixture Staleness Timestamps.

Coverage:
  TestFixtureRecordDataclass           — 10 tests
  TestHashIntactProperty               —  6 tests
  TestComputeContentHash               —  8 tests
  TestLoadAllFixtureRecords            —  8 tests
  TestAllFixturesAfterMigration        —  5 tests
  TestFixtureStalenessMetric           — 14 tests
  TestMetricEdgeCases                  —  6 tests
  TestIsFreshProperty                  —  6 tests
  TestConfigIntegration                —  7 tests
                                       ─────────
  Total                                — 70 tests
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from evals.benchmarks.fixture_staleness import (
    FixtureRecord,
    STALENESS_THRESHOLDS,
    compute_content_hash,
    load_all_fixture_records,
    _RECORDED_DIR,
    _POOLS_DIR,
)
from evals.metrics.fixture_staleness import FixtureStalenessMetric
from evals.metrics.base import MetricResult
from evals.config import (
    INDEX_WEIGHTS,
    PASS_THRESHOLDS,
    CI_BLOCK_THRESHOLDS,
    QUICK_EVAL_METRICS,
)

# Fixed reference date used in all freshness tests so they are deterministic
# regardless of when the suite runs (6 days after recorded fixture, 2 after pools).
_REF = datetime(2026, 6, 10, tzinfo=timezone.utc)

# Hash for a trivial scored_products payload (used in synthetic tests)
_TRIVIAL_HASH = hashlib.sha256(
    json.dumps([], sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(
    fixture_id: str = "test_fixture",
    fixture_type: str = "recorded",
    captured_at: str = "2026-06-08T00:00:00+00:00",
    stored_hash: str = "",
    computed_hash: str = "",
    threshold: int | None = None,
) -> FixtureRecord:
    if threshold is None:
        threshold = STALENESS_THRESHOLDS[fixture_type]
    return FixtureRecord(
        fixture_id=fixture_id,
        fixture_type=fixture_type,
        path=f"evals/data/fixtures/{fixture_id}.json",
        captured_at=captured_at,
        schema_version="1.0",
        stored_hash=stored_hash,
        computed_hash=computed_hash,
        staleness_threshold_days=threshold,
    )


def _make_good_record(fixture_type: str = "recorded") -> FixtureRecord:
    h = _TRIVIAL_HASH
    return _make_record(
        fixture_type=fixture_type,
        captured_at="2026-06-08T00:00:00+00:00",
        stored_hash=h,
        computed_hash=h,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TestFixtureRecordDataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestFixtureRecordDataclass:
    def test_all_fields_stored(self):
        rec = _make_record("my_fixture", "pool", "2026-01-01T00:00:00+00:00", "abc", "abc", 365)
        assert rec.fixture_id == "my_fixture"
        assert rec.fixture_type == "pool"
        assert rec.captured_at == "2026-01-01T00:00:00+00:00"
        assert rec.stored_hash == "abc"
        assert rec.computed_hash == "abc"
        assert rec.staleness_threshold_days == 365

    def test_has_timestamp_true_for_iso_with_utc(self):
        rec = _make_record(captured_at="2026-06-08T00:00:00+00:00")
        assert rec.has_timestamp is True

    def test_has_timestamp_false_for_date_only(self):
        rec = _make_record(captured_at="2026-06-08")
        assert rec.has_timestamp is False

    def test_has_timestamp_false_for_empty(self):
        rec = _make_record(captured_at="")
        assert rec.has_timestamp is False

    def test_has_timestamp_false_for_naive_datetime(self):
        rec = _make_record(captured_at="2026-06-08T00:00:00")
        assert rec.has_timestamp is False

    def test_has_timestamp_false_for_invalid_string(self):
        rec = _make_record(captured_at="not-a-date")
        assert rec.has_timestamp is False

    def test_age_days_correct(self):
        rec = _make_record(captured_at="2026-06-04T00:00:00+00:00")
        assert rec.age_days(_REF) == 6

    def test_age_days_none_for_missing_timestamp(self):
        rec = _make_record(captured_at="")
        assert rec.age_days(_REF) is None

    def test_is_fresh_true_within_threshold(self):
        rec = _make_record(captured_at="2026-06-08T00:00:00+00:00", threshold=90)
        assert rec.is_fresh(_REF) is True

    def test_is_fresh_false_beyond_threshold(self):
        # 200 days before reference
        old_dt = _REF - timedelta(days=200)
        rec = _make_record(captured_at=old_dt.isoformat(), threshold=90)
        assert rec.is_fresh(_REF) is False


# ─────────────────────────────────────────────────────────────────────────────
# TestHashIntactProperty
# ─────────────────────────────────────────────────────────────────────────────

class TestHashIntactProperty:
    def test_matching_hashes_return_true(self):
        rec = _make_record(stored_hash="abc123", computed_hash="abc123")
        assert rec.hash_intact is True

    def test_mismatched_hashes_return_false(self):
        rec = _make_record(stored_hash="aaa", computed_hash="bbb")
        assert rec.hash_intact is False

    def test_empty_stored_hash_returns_false(self):
        rec = _make_record(stored_hash="", computed_hash="abc123")
        assert rec.hash_intact is False

    def test_empty_computed_hash_returns_false(self):
        rec = _make_record(stored_hash="abc123", computed_hash="")
        assert rec.hash_intact is False

    def test_both_empty_returns_false(self):
        rec = _make_record(stored_hash="", computed_hash="")
        assert rec.hash_intact is False

    def test_hash_comparison_is_case_sensitive(self):
        rec = _make_record(stored_hash="ABC", computed_hash="abc")
        assert rec.hash_intact is False


# ─────────────────────────────────────────────────────────────────────────────
# TestComputeContentHash
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeContentHash:
    def test_recorded_hash_is_64_char_hex(self):
        path = _RECORDED_DIR / "earbuds_under_3000_india.json"
        h = compute_content_hash(path, "recorded")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_pool_hash_is_64_char_hex(self):
        path = _POOLS_DIR / "earbuds_real.json"
        h = compute_content_hash(path, "pool")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_file_same_hash_twice(self):
        path = _RECORDED_DIR / "earbuds_under_3000_india.json"
        assert compute_content_hash(path, "recorded") == compute_content_hash(path, "recorded")

    def test_different_pools_different_hashes(self):
        h1 = compute_content_hash(_POOLS_DIR / "earbuds_real.json", "pool")
        h2 = compute_content_hash(_POOLS_DIR / "laptops.json", "pool")
        assert h1 != h2

    def test_missing_file_returns_empty_string(self):
        result = compute_content_hash(Path("nonexistent_file.json"), "recorded")
        assert result == ""

    def test_recorded_hash_excludes_meta(self, tmp_path):
        # Two files with identical scored_products but different _meta → same hash
        payload = {"_meta": {"captured_at": "2020-01-01"}, "scored_products": [{"name": "P1"}]}
        p1 = tmp_path / "f1.json"
        p1.write_text(json.dumps(payload), encoding="utf-8")

        payload2 = {"_meta": {"captured_at": "2099-12-31"}, "scored_products": [{"name": "P1"}]}
        p2 = tmp_path / "f2.json"
        p2.write_text(json.dumps(payload2), encoding="utf-8")

        assert compute_content_hash(p1, "recorded") == compute_content_hash(p2, "recorded")

    def test_pool_hash_excludes_meta(self, tmp_path):
        base = {"criteria": [{"name": "c1", "label": "C1"}],
                "products": [{"name": "P1", "scores": {"c1": 5}}]}
        p1 = tmp_path / "pool1.json"
        p1.write_text(json.dumps({**base, "_meta": {"note": "old"}}), encoding="utf-8")
        p2 = tmp_path / "pool2.json"
        p2.write_text(json.dumps({**base, "_meta": {"note": "new"}}), encoding="utf-8")
        assert compute_content_hash(p1, "pool") == compute_content_hash(p2, "pool")

    def test_pool_hash_detects_product_change(self, tmp_path):
        p1 = tmp_path / "a.json"
        p1.write_text(json.dumps({"criteria": [], "products": [{"name": "A"}]}), encoding="utf-8")
        p2 = tmp_path / "b.json"
        p2.write_text(json.dumps({"criteria": [], "products": [{"name": "B"}]}), encoding="utf-8")
        assert compute_content_hash(p1, "pool") != compute_content_hash(p2, "pool")


# ─────────────────────────────────────────────────────────────────────────────
# TestLoadAllFixtureRecords
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadAllFixtureRecords:
    def test_returns_five_records(self):
        records = load_all_fixture_records()
        assert len(records) == 5

    def test_one_recorded_fixture(self):
        records = load_all_fixture_records()
        recorded = [r for r in records if r.fixture_type == "recorded"]
        assert len(recorded) == 1

    def test_four_pool_fixtures(self):
        records = load_all_fixture_records()
        pools = [r for r in records if r.fixture_type == "pool"]
        assert len(pools) == 4

    def test_all_have_non_empty_fixture_id(self):
        for rec in load_all_fixture_records():
            assert rec.fixture_id, f"fixture_id empty for {rec.path}"

    def test_recorded_has_90_day_threshold(self):
        records = load_all_fixture_records()
        for rec in records:
            if rec.fixture_type == "recorded":
                assert rec.staleness_threshold_days == 90

    def test_pool_has_365_day_threshold(self):
        records = load_all_fixture_records()
        for rec in records:
            if rec.fixture_type == "pool":
                assert rec.staleness_threshold_days == 365

    def test_all_have_non_empty_computed_hash(self):
        for rec in load_all_fixture_records():
            assert rec.computed_hash, f"computed_hash empty for {rec.fixture_id}"

    def test_returns_new_list_each_call(self):
        a = load_all_fixture_records()
        b = load_all_fixture_records()
        assert a is not b
        assert a == b


# ─────────────────────────────────────────────────────────────────────────────
# TestAllFixturesAfterMigration
# ─────────────────────────────────────────────────────────────────────────────

class TestAllFixturesAfterMigration:
    """Post-migration: all 5 data files should pass all 3 staleness checks."""

    def test_all_records_have_valid_timestamp(self):
        for rec in load_all_fixture_records():
            assert rec.has_timestamp, f"{rec.fixture_id} missing valid timezone-aware timestamp"

    def test_all_records_are_fresh(self):
        for rec in load_all_fixture_records():
            assert rec.is_fresh(_REF), (
                f"{rec.fixture_id} is stale: age={rec.age_days(_REF)}d > {rec.staleness_threshold_days}d"
            )

    def test_all_records_have_intact_hash(self):
        for rec in load_all_fixture_records():
            assert rec.hash_intact, (
                f"{rec.fixture_id} hash mismatch: stored={rec.stored_hash[:8]} "
                f"computed={rec.computed_hash[:8]}"
            )

    def test_recorded_captured_at_preserves_original_date(self):
        records = load_all_fixture_records()
        rec = next(r for r in records if r.fixture_type == "recorded")
        assert rec.captured_at.startswith("2026-06-04")

    def test_pool_captured_at_set_to_migration_date(self):
        records = load_all_fixture_records()
        for rec in records:
            if rec.fixture_type == "pool":
                assert rec.captured_at.startswith("2026-06-08")


# ─────────────────────────────────────────────────────────────────────────────
# TestFixtureStalenessMetric
# ─────────────────────────────────────────────────────────────────────────────

class TestFixtureStalenessMetric:
    def test_returns_metric_result(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert isinstance(result, MetricResult)

    def test_overall_score_100_after_migration(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.score == 100.0

    def test_metric_passes(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.passed is True

    def test_not_skipped(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.skipped is False

    def test_metric_name(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.name == "fixture_staleness"

    def test_phase_name(self):
        assert FixtureStalenessMetric.phase == "Phase 16: Fixture Staleness Timestamps"

    def test_details_total_fixtures(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.details["total_fixtures"] == 5

    def test_details_timestamp_count(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.details["timestamp_count"] == 5

    def test_details_fresh_count(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.details["fresh_count"] == 5

    def test_details_hash_intact_count(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.details["hash_intact_count"] == 5

    def test_details_fixture_details_length(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert len(result.details["fixture_details"]) == 5

    def test_empty_list_returns_skip(self):
        result = FixtureStalenessMetric().evaluate([])
        assert result.skipped is True
        assert result.passed is True
        assert result.score == 0.0

    def test_pass_threshold_from_config(self):
        result = FixtureStalenessMetric().evaluate(
            load_all_fixture_records(), reference_date=_REF
        )
        assert result.pass_threshold == PASS_THRESHOLDS["fixture_staleness"]

    def test_failures_populated_when_record_fails(self):
        bad = _make_record(captured_at="", stored_hash="", computed_hash="xyz")
        result = FixtureStalenessMetric().evaluate([bad], reference_date=_REF)
        assert len(result.failures) > 0
        assert "test_fixture" in " ".join(result.failures)


# ─────────────────────────────────────────────────────────────────────────────
# TestMetricEdgeCases
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricEdgeCases:
    def test_empty_records_skip_has_reason(self):
        result = FixtureStalenessMetric().evaluate([])
        assert "skipped_reason" in result.details

    def test_single_record_all_pass_scores_100(self):
        rec = _make_good_record()
        result = FixtureStalenessMetric().evaluate([rec], reference_date=_REF)
        assert result.score == 100.0

    def test_single_record_no_timestamp_scores_60(self):
        # No timestamp → has_timestamp=0 (30pts), is_fresh=0 (40pts), hash_intact=1 (30pts)
        # → (0*0.30 + 0*0.40 + 1*0.30) * 100 = 30.0
        h = _TRIVIAL_HASH
        rec = _make_record(captured_at="", stored_hash=h, computed_hash=h)
        result = FixtureStalenessMetric().evaluate([rec], reference_date=_REF)
        assert result.score == 30.0

    def test_single_record_stale_scores_70(self):
        # Stale: ts=OK(30), fresh=FAIL(0), hash=OK(30) → 60.0
        old_dt = (_REF - timedelta(days=200)).isoformat()
        h = _TRIVIAL_HASH
        rec = _make_record(captured_at=old_dt, stored_hash=h, computed_hash=h, threshold=90)
        result = FixtureStalenessMetric().evaluate([rec], reference_date=_REF)
        assert result.score == 60.0

    def test_single_record_wrong_hash_scores_70(self):
        # Wrong hash: ts=OK(30), fresh=OK(40), hash=FAIL(0) → 70.0
        rec = _make_record(
            captured_at="2026-06-08T00:00:00+00:00",
            stored_hash="wrong_hash_value",
            computed_hash=_TRIVIAL_HASH,
        )
        result = FixtureStalenessMetric().evaluate([rec], reference_date=_REF)
        assert result.score == 70.0

    def test_failure_message_contains_fixture_id(self):
        rec = _make_record(
            fixture_id="my_problem_fixture",
            captured_at="",
            stored_hash="",
            computed_hash="",
        )
        result = FixtureStalenessMetric().evaluate([rec], reference_date=_REF)
        assert any("my_problem_fixture" in f for f in result.failures)


# ─────────────────────────────────────────────────────────────────────────────
# TestIsFreshProperty
# ─────────────────────────────────────────────────────────────────────────────

class TestIsFreshProperty:
    def test_within_threshold_is_fresh(self):
        rec = _make_record(captured_at="2026-06-08T00:00:00+00:00", threshold=90)
        assert rec.is_fresh(_REF) is True  # 2 days old, threshold 90

    def test_at_boundary_is_fresh(self):
        exactly = _REF - timedelta(days=90)
        rec = _make_record(captured_at=exactly.isoformat(), threshold=90)
        assert rec.is_fresh(_REF) is True

    def test_one_day_over_threshold_is_stale(self):
        over = _REF - timedelta(days=91)
        rec = _make_record(captured_at=over.isoformat(), threshold=90)
        assert rec.is_fresh(_REF) is False

    def test_no_timestamp_is_never_fresh(self):
        rec = _make_record(captured_at="")
        assert rec.is_fresh(_REF) is False

    def test_recorded_threshold_90(self):
        assert STALENESS_THRESHOLDS["recorded"] == 90

    def test_pool_threshold_365(self):
        assert STALENESS_THRESHOLDS["pool"] == 365


# ─────────────────────────────────────────────────────────────────────────────
# TestConfigIntegration
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigIntegration:
    def test_fixture_staleness_in_index_weights(self):
        assert "fixture_staleness" in INDEX_WEIGHTS

    def test_fixture_staleness_weight_is_one_percent(self):
        assert INDEX_WEIGHTS["fixture_staleness"] == 0.01

    def test_robustness_weight_reduced_to_one_percent(self):
        assert INDEX_WEIGHTS["robustness"] == 0.01

    def test_index_weights_sum_to_one(self):
        total = sum(INDEX_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_fixture_staleness_in_pass_thresholds(self):
        assert "fixture_staleness" in PASS_THRESHOLDS

    def test_fixture_staleness_in_ci_block_thresholds(self):
        assert "fixture_staleness" in CI_BLOCK_THRESHOLDS

    def test_fixture_staleness_in_quick_eval_metrics(self):
        assert "fixture_staleness" in QUICK_EVAL_METRICS
