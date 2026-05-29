"""
Phase 9: Robustness

Tests that injected adversarial content cannot corrupt rankings.
In offline mode: verifies that the pure-Python scoring math ignores injected text in
praise/complaint/evidence fields (the scores come from criterion_scores dict, not text).
If the scoring engine is text-injection-proof, the expected_safe_winner always wins.
"""

from __future__ import annotations
from evals.benchmarks.base import AdversarialScenario
from evals.engine import build_scored_products
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class RobustnessMetric(BaseMetric):
    name = "robustness"
    phase = "Phase 9: Adversarial Robustness"

    def evaluate(self, adversarial_scenarios: list[AdversarialScenario], **kwargs) -> MetricResult:
        results = []

        for scenario in adversarial_scenarios:
            scored = build_scored_products(scenario.safe_products, scenario.safe_rubric)
            rank1 = scored[0]["name"] if scored else ""

            # The safe winner should always beat the attack target
            safe_winner_wins = rank1 == scenario.expected_safe_winner
            attack_target_rank = next(
                (i + 1 for i, p in enumerate(scored) if p["name"] == scenario.attack_target),
                len(scored) + 1,
            )
            safe_rank = next(
                (i + 1 for i, p in enumerate(scored) if p["name"] == scenario.expected_safe_winner),
                len(scored) + 1,
            )

            passed = safe_winner_wins and (safe_rank < attack_target_rank)
            failures = []

            if not safe_winner_wins:
                failures.append(
                    f"attack_succeeded: '{rank1}' won instead of '{scenario.expected_safe_winner}'"
                )
            elif attack_target_rank < safe_rank:
                failures.append(
                    f"partial_attack: '{scenario.attack_target}' ranks {attack_target_rank}, "
                    f"safe winner ranks {safe_rank}"
                )

            results.append({
                "id": scenario.id,
                "name": scenario.name,
                "attack_type": scenario.attack_type,
                "rank1": rank1,
                "expected_safe_winner": scenario.expected_safe_winner,
                "attack_target": scenario.attack_target,
                "attack_target_rank": attack_target_rank,
                "safe_rank": safe_rank,
                "passed": passed,
                "failures": failures,
            })

        passing = [r for r in results if r["passed"]]
        score = (len(passing) / len(results) * 100) if results else 0.0
        threshold = PASS_THRESHOLDS[self.name]

        # Group by attack type
        by_type: dict[str, list[bool]] = {}
        for r in results:
            by_type.setdefault(r["attack_type"], []).append(r["passed"])
        type_stats = {
            t: {"pass_rate": round(sum(v) / len(v) * 100, 1), "total": len(v)}
            for t, v in by_type.items()
        }

        failures_list = [
            f"[{r['id']}] {f}"
            for r in results if not r["passed"]
            for f in r["failures"]
        ]

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": len(results),
                "passed": len(passing),
                "by_attack_type": type_stats,
                "scenarios": [
                    {"id": r["id"], "attack_type": r["attack_type"],
                     "passed": r["passed"], "rank1": r["rank1"]}
                    for r in results
                ],
            },
            failures=failures_list,
        )
