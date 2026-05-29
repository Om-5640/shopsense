"""
Phase 2: Recommendation Quality

Measures whether the correct product wins given each user's rubric.
Sub-metrics:
  - rank_1_accuracy      : expected product is at rank 1
  - constraint_adherence : hard constraint products not at rank 1
  - top2_coverage        : expected_top_2 products appear in top 2
  - score_margin         : winner's margin over rank-2 (proxy for decisiveness)
"""

from __future__ import annotations
from evals.benchmarks.base import OfflineScenario
from evals.engine import build_scored_products, rank_names, rank_of
from evals.metrics.base import BaseMetric, MetricResult, ScenarioResult
from evals.config import PASS_THRESHOLDS


class RecommendationQualityMetric(BaseMetric):
    name = "recommendation_quality"
    phase = "Phase 2: Recommendation Quality"

    def evaluate(self, scenarios: list[OfflineScenario], **kwargs) -> MetricResult:
        results: list[ScenarioResult] = []

        for s in scenarios:
            scored = build_scored_products(s.products, s.rubric_weights)
            ranks = rank_names(scored)
            rank1 = ranks[0] if ranks else ""
            failures: list[str] = []

            # Sub-metric 1: rank-1 accuracy
            if rank1 != s.expected_rank_1:
                failures.append(
                    f"rank_1: got '{rank1}', expected '{s.expected_rank_1}'"
                )

            # Sub-metric 2: constraint — none of expected_rank_1_not should be rank 1
            for banned in s.expected_rank_1_not:
                if rank1 == banned:
                    failures.append(f"constraint_violation: '{banned}' should not be rank 1")

            # Sub-metric 3: top-2 coverage
            for req in s.expected_top_2:
                if req not in ranks[:2]:
                    failures.append(f"top2_miss: '{req}' not in top 2 (got {ranks[:2]})")

            # Sub-metric 4: score margin (winner should be decisively ahead)
            winner_pct = scored[0]["percentage"] if scored else 0
            second_pct = scored[1]["percentage"] if len(scored) > 1 else 0
            margin = winner_pct - second_pct

            passed = len(failures) == 0
            results.append(ScenarioResult(
                scenario_id=s.id,
                scenario_name=s.name,
                tags=s.tags,
                passed=passed,
                score=100.0 if passed else 0.0,
                failures=failures,
                details={"rank1": rank1, "expected": s.expected_rank_1, "margin": round(margin, 1)},
            ))

        passing = [r for r in results if r.passed]
        score = (len(passing) / len(results) * 100) if results else 0.0
        threshold = PASS_THRESHOLDS[self.name]
        failures_list = [
            f"[{r.scenario_id}] {f}"
            for r in results if not r.passed
            for f in r.failures
        ]

        # Breakdown by tag
        tag_stats = _tag_breakdown(results)

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": len(results),
                "passed": len(passing),
                "failed": len(results) - len(passing),
                "by_tag": tag_stats,
                "scenario_results": [
                    {"id": r.scenario_id, "name": r.scenario_name,
                     "passed": r.passed, "details": r.details}
                    for r in results
                ],
            },
            failures=failures_list[:20],
        )


def _tag_breakdown(results: list[ScenarioResult]) -> dict[str, dict]:
    tags: dict[str, list[bool]] = {}
    for r in results:
        for tag in r.tags:
            tags.setdefault(tag, []).append(r.passed)
    return {
        tag: {"pass_rate": round(sum(v) / len(v) * 100, 1), "total": len(v)}
        for tag, v in tags.items()
    }
