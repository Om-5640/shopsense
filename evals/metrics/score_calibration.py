"""
Phase 12: Score Calibration

Detects LLM grade-inflation in recorded pipeline-output fixtures.
Score = (passing calibration checks / total checks) × 100.

A score of 100 means every recorded fixture passes all four calibration checks
(spread, inflation, discrimination, low-range usage).  A score below the pass
threshold means the LLM scorer exhibits leniency bias or compression that
undermines the trustworthiness of rankings.
"""

from __future__ import annotations

from evals.benchmarks.score_calibration import CalibrationSuite
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class ScoreCalibrationMetric(BaseMetric):
    name = "score_calibration"
    phase = "Phase 12: Score Calibration"

    def evaluate(
        self,
        calibration_suites: list[CalibrationSuite],
        **kwargs,
    ) -> MetricResult:
        threshold = PASS_THRESHOLDS.get(self.name, 70.0)

        if not calibration_suites:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="no recorded fixtures available",
            )

        active = [s for s in calibration_suites if not s.skipped]
        if not active:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason=(
                    f"all {len(calibration_suites)} suite(s) skipped "
                    "(not enough products per fixture)"
                ),
            )

        total_checks = sum(len(s.checks) for s in active)
        passed_checks = sum(1 for s in active for c in s.checks if c.passed)
        score = round(passed_checks / total_checks * 100, 1) if total_checks > 0 else 100.0

        failures_list: list[str] = []
        suite_details: list[dict] = []

        for suite in calibration_suites:
            info: dict = {
                "suite_id": suite.suite_id,
                "product_count": suite.product_count,
                "criterion_count": suite.criterion_count,
                "skipped": suite.skipped,
                "passed": suite.passed,
            }
            if suite.skipped:
                info["skip_reason"] = suite.skip_reason
            else:
                info["pass_rate"] = round(suite.pass_rate * 100, 1)
                info["checks"] = [
                    {
                        "name": c.name,
                        "passed": c.passed,
                        "value": c.value,
                        "threshold": c.threshold,
                        "description": c.description,
                    }
                    for c in suite.checks
                ]
                for failure in suite.failures:
                    failures_list.append(f"[{suite.suite_id}] {failure}")

            suite_details.append(info)

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_suites": len(calibration_suites),
                "active_suites": len(active),
                "skipped_suites": len(calibration_suites) - len(active),
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "suites": suite_details,
            },
            failures=failures_list,
        )
