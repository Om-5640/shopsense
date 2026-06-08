"""
Fix 18: Extraction Recall Metric.

Measures whether normalize_analysis() preserves all expected products through
deduplication, capping, and name normalization.

For each ExtractionScenario the metric:
  1. Calls normalize_analysis(scenario.analysis_json)
  2. Extracts the product names from the result
  3. Computes recall  = |found ∩ expected| / |expected|
  4. Computes precision = |found ∩ expected| / |found|  (guards against over-extraction)
  5. Computes F1 = harmonic mean of recall + precision
  6. Verifies no unexpected products were hallucinated

Per-scenario score = F1 × 100 (or 100.0 when expected is empty)
Overall metric score = mean of per-scenario scores.

All logic is deterministic pure-Python — zero LLM calls.

Import note: normalize_analysis lives in the project root (analysis_normalizer.py).
The metric imports it via sys.path so it works in both `python -m evals` (run from
project root) and direct pytest invocations.
"""

from __future__ import annotations
import sys
import os
from pathlib import Path

from evals.benchmarks.extraction_recall import ExtractionScenario
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS

# ── Import normalize_analysis from project root ───────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from analysis_normalizer import normalize_analysis as _normalize  # type: ignore[import]
    _HAS_NORMALIZER = True
except ImportError:
    _normalize = None  # type: ignore[assignment]
    _HAS_NORMALIZER = False


def _canonical(name: str) -> str:
    """Lowercase-strip for fuzzy name matching — mirrors _canonical_key in normalizer."""
    import re
    return re.sub(r"[\W_]", "", name.lower())


def _names_from_result(result: dict) -> set[str]:
    """Extract the set of canonical product names from a normalize_analysis result."""
    products = result.get("products") or []
    return {_canonical(p.get("name", "")) for p in products if p.get("name")}


class ExtractionRecallMetric(BaseMetric):
    name = "extraction_recall"
    phase = "Fix 18: Extraction Precision/Recall"

    def evaluate(
        self,
        scenarios: list[ExtractionScenario],
        **kwargs,
    ) -> MetricResult:
        threshold = PASS_THRESHOLDS.get(self.name, 90.0)

        if not _HAS_NORMALIZER:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="analysis_normalizer not importable — run from project root",
            )

        if not scenarios:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="no extraction scenarios provided",
            )

        failures: list[str] = []
        scenario_details: list[dict] = []
        per_scores: list[float] = []

        for sc in scenarios:
            result = _normalize(sc.analysis_json)
            found_canonical = _names_from_result(result)

            expected_canonical = {_canonical(e) for e in sc.expected_products}
            unexpected_canonical = {_canonical(u) for u in sc.unexpected_products}

            # Vacuous case: no expected products → perfect score (empty corpus is fine)
            if not expected_canonical:
                per_scores.append(100.0)
                scenario_details.append({
                    "id": sc.id,
                    "description": sc.description,
                    "expected_count": 0,
                    "found_count": len(found_canonical),
                    "recall": 1.0,
                    "precision": 1.0,
                    "f1": 1.0,
                    "f1_score": 100.0,
                    "missing": [],
                    "hallucinated": [],
                })
                continue

            # Recall: did we find everything expected?
            found_expected = found_canonical & expected_canonical
            recall = len(found_expected) / len(expected_canonical)

            # Precision: did we invent products?
            if found_canonical:
                precision = len(found_expected) / len(found_canonical)
            else:
                precision = 0.0

            # F1
            if recall + precision > 0:
                f1 = 2 * recall * precision / (recall + precision)
            else:
                f1 = 0.0

            f1_score = round(f1 * 100.0, 1)
            per_scores.append(f1_score)

            missing = [e for e in sc.expected_products if _canonical(e) not in found_canonical]
            hallucinated = [name for name in sc.unexpected_products
                            if _canonical(name) in found_canonical]

            if f1_score < sc.min_recall * 100.0 - 0.1:  # small epsilon for float safety
                failures.append(
                    f"[{sc.id}] F1={f1_score:.1f} "
                    f"(recall={recall:.3f}, precision={precision:.3f}) "
                    f"missing={missing}"
                )

            if hallucinated:
                failures.append(
                    f"[{sc.id}] hallucinated unexpected products: {hallucinated}"
                )

            scenario_details.append({
                "id": sc.id,
                "description": sc.description,
                "expected_count": len(expected_canonical),
                "found_count": len(found_canonical),
                "recall": round(recall, 4),
                "precision": round(precision, 4),
                "f1": round(f1, 4),
                "f1_score": f1_score,
                "missing": missing,
                "hallucinated": hallucinated,
            })

        score = round(sum(per_scores) / len(per_scores), 1) if per_scores else 0.0
        perfect = sum(1 for d in scenario_details if d["f1_score"] >= 99.9)

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": len(scenarios),
                "perfect_recall_scenarios": perfect,
                "avg_recall": round(
                    sum(d["recall"] for d in scenario_details) / len(scenario_details), 4
                ),
                "avg_precision": round(
                    sum(d["precision"] for d in scenario_details) / len(scenario_details), 4
                ),
                "scenario_details": scenario_details,
            },
            failures=failures,
        )
