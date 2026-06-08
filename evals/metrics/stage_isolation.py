"""
Phase 10: Stage Fault Injection

For each fault scenario, injects a known pipeline corruption and verifies that
the final ranked output changes detectably.  If the rank does NOT change after
a corruption the pipeline has a blind spot in that stage.

Score = (detected / applicable) × 100
Target: 100 % of applicable faults must produce a detectable rank signal.
A result below the CI block threshold means inject_fault() or build_scored_products()
has a regression.
"""

from __future__ import annotations

from evals.benchmarks.fault_injection import FaultScenario, inject_fault, is_detected
from evals.engine import build_scored_products
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class StageIsolationMetric(BaseMetric):
    name = "stage_isolation"
    phase = "Phase 10: Stage Fault Injection"

    def evaluate(self, fault_scenarios: list[FaultScenario], **kwargs) -> MetricResult:
        if not fault_scenarios:
            return MetricResult.skip(
                name=self.name,
                threshold=PASS_THRESHOLDS.get(self.name, 90.0),
                reason="no fault scenarios provided",
            )

        threshold = PASS_THRESHOLDS.get(self.name, 90.0)
        results: list[dict] = []
        not_applicable: int = 0
        failures_list: list[str] = []

        for scenario in fault_scenarios:
            baseline_products, corrupted_products = inject_fault(scenario)

            baseline_ranked = build_scored_products(baseline_products, scenario.rubric)
            corrupted_ranked = build_scored_products(corrupted_products, scenario.rubric)

            # Structurally impossible: need at least 2 products to change rank
            if len(baseline_ranked) < 2:
                not_applicable += 1
                continue

            detected, explanation = is_detected(
                scenario, baseline_ranked, corrupted_ranked
            )

            results.append({
                "id": scenario.id,
                "fault_type": scenario.fault_type.value,
                "target_product": scenario.target_product,
                "detection_mode": scenario.detection,
                "detected": detected,
                "explanation": explanation,
                "source_fixture": scenario.source_fixture,
            })

            if not detected:
                failures_list.append(f"[{scenario.id}] {explanation}")

        applicable = len(results)
        detected_count = sum(1 for r in results if r["detected"])

        score = round(detected_count / applicable * 100, 1) if applicable > 0 else 0.0

        # Group detection rates by fault type
        by_type: dict[str, dict] = {}
        for r in results:
            ft = r["fault_type"]
            if ft not in by_type:
                by_type[ft] = {"detected": 0, "total": 0}
            by_type[ft]["total"] += 1
            if r["detected"]:
                by_type[ft]["detected"] += 1
        for stats in by_type.values():
            stats["detection_rate"] = round(
                stats["detected"] / stats["total"] * 100 if stats["total"] > 0 else 0.0, 1
            )

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": applicable + not_applicable,
                "applicable": applicable,
                "not_applicable": not_applicable,
                "detected": detected_count,
                "by_fault_type": by_type,
                "scenarios": [
                    {
                        "id": r["id"],
                        "fault_type": r["fault_type"],
                        "detected": r["detected"],
                        "explanation": r["explanation"],
                    }
                    for r in results
                ],
            },
            failures=failures_list,
        )
