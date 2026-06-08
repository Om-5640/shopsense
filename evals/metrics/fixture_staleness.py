"""
Phase 16: Fixture Staleness Timestamps.

Validates that every benchmark data file (recorded pipeline fixtures and pool files)
carries a fresh, correct ``_meta`` block with:
  - a valid ISO datetime timestamp WITH timezone (not just a date)
  - an age within the type-appropriate threshold
  - a content hash that matches the file's actual non-meta data

Three checks per fixture (weights: 30 / 40 / 30):
  1. has_timestamp  (30 pts) — captured_at is a valid ISO datetime with timezone
  2. is_fresh       (40 pts) — age from reference date <= staleness_threshold_days
  3. hash_intact    (30 pts) — stored content_hash matches SHA-256 of file content

Per-fixture score  = (has_timestamp×0.30 + is_fresh×0.40 + hash_intact×0.30) × 100
Overall metric score = mean of per-fixture scores.

All checks are deterministic pure-Python — zero LLM calls.
The optional ``reference_date`` parameter lets tests supply a fixed anchor so
freshness checks are reproducible regardless of when the suite runs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from evals.benchmarks.fixture_staleness import FixtureRecord
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class FixtureStalenessMetric(BaseMetric):
    name = "fixture_staleness"
    phase = "Phase 16: Fixture Staleness Timestamps"

    def evaluate(
        self,
        records: list[FixtureRecord],
        reference_date: datetime | None = None,
        **kwargs,
    ) -> MetricResult:
        """
        Evaluate staleness and integrity of all fixture records.

        Args:
            records:        List of FixtureRecord from load_all_fixture_records().
            reference_date: Anchor for freshness checks (default: now UTC).
                            Pass a fixed datetime in tests for determinism.
        """
        threshold = PASS_THRESHOLDS.get(self.name, 80.0)
        ref = reference_date or datetime.now(timezone.utc)

        if not records:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="no fixture records found",
            )

        failures: list[str] = []
        fixture_details: list[dict] = []
        per_scores: list[float] = []

        for rec in records:
            ts_ok   = rec.has_timestamp
            fresh   = rec.is_fresh(ref)
            hash_ok = rec.hash_intact

            per_score = (
                (1.0 if ts_ok   else 0.0) * 0.30
                + (1.0 if fresh   else 0.0) * 0.40
                + (1.0 if hash_ok else 0.0) * 0.30
            ) * 100.0
            per_scores.append(per_score)

            if not ts_ok:
                failures.append(
                    f"[{rec.fixture_id}] has_timestamp FAIL — "
                    f"captured_at={rec.captured_at!r} is missing or lacks timezone"
                )
            if not fresh:
                age = rec.age_days(ref)
                failures.append(
                    f"[{rec.fixture_id}] is_fresh FAIL — "
                    f"age={age}d exceeds threshold={rec.staleness_threshold_days}d "
                    f"(type={rec.fixture_type})"
                )
            if not hash_ok:
                failures.append(
                    f"[{rec.fixture_id}] hash_intact FAIL — "
                    f"stored={rec.stored_hash[:16] or '(empty)'}… "
                    f"computed={rec.computed_hash[:16] or '(empty)'}…"
                )

            fixture_details.append({
                "fixture_id":    rec.fixture_id,
                "fixture_type":  rec.fixture_type,
                "path":          rec.path,
                "captured_at":   rec.captured_at,
                "schema_version": rec.schema_version,
                "age_days":      rec.age_days(ref),
                "threshold_days": rec.staleness_threshold_days,
                "per_score":     round(per_score, 1),
                "has_timestamp": ts_ok,
                "is_fresh":      fresh,
                "hash_intact":   hash_ok,
            })

        score = round(sum(per_scores) / len(per_scores), 1)

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_fixtures":    len(records),
                "timestamp_count":   sum(1 for d in fixture_details if d["has_timestamp"]),
                "fresh_count":       sum(1 for d in fixture_details if d["is_fresh"]),
                "hash_intact_count": sum(1 for d in fixture_details if d["hash_intact"]),
                "fixture_details":   fixture_details,
            },
            failures=failures,
        )
