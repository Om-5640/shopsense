"""
Phase 13: Composite Intelligence Index

Computes a single 0-100 score from weighted component metrics.
This is the primary headline number tracked over time.
"""

from __future__ import annotations
from evals.config import INDEX_WEIGHTS
from evals.metrics.base import MetricResult


def compute_index(metric_results: dict[str, MetricResult]) -> float:
    """
    Compute Intelligence Index as weighted average of metric scores.
    Metrics not present in results are excluded from the weighted average
    (weight redistributed proportionally to present metrics).
    """
    present_weights = {
        k: v for k, v in INDEX_WEIGHTS.items()
        if k in metric_results
    }
    if not present_weights:
        return 0.0

    total_weight = sum(present_weights.values())
    weighted_sum = sum(
        metric_results[k].score * w
        for k, w in present_weights.items()
    )
    return round(weighted_sum / total_weight, 1)


def compute_index_breakdown(metric_results: dict[str, MetricResult]) -> dict:
    """Return detailed index breakdown for reports."""
    contributions = {}
    for key, result in metric_results.items():
        weight = INDEX_WEIGHTS.get(key, 0)
        contributions[key] = {
            "score": result.score,
            "weight": weight,
            "contribution": round(result.score * weight, 2),
            "passed": result.passed,
            "grade": result.grade,
        }

    index = compute_index(metric_results)
    return {
        "intelligence_index": index,
        "grade": _grade(index),
        "components": contributions,
        "weights_sum": round(sum(INDEX_WEIGHTS[k] for k in metric_results if k in INDEX_WEIGHTS), 3),
    }


def _grade(index: float) -> str:
    if index >= 90: return "A+"
    if index >= 80: return "A"
    if index >= 70: return "B"
    if index >= 60: return "C"
    if index >= 50: return "D"
    return "F"
