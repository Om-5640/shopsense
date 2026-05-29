"""
Phase 4: Personalization Strength

Measures whether different personas for the SAME query produce meaningfully different rankings.
A system with zero personalization gives the same rank-1 to every user.

Personalization Strength Score = diversity of rank-1 winners across personas.
Ideal: every persona has a different rank-1. Worst case: all personas agree.
"""

from __future__ import annotations
from evals.benchmarks.base import PersonalizationTest
from evals.engine import build_scored_products, rank_names
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class PersonalizationStrengthMetric(BaseMetric):
    name = "personalization_strength"
    phase = "Phase 4: Personalization Evals"

    def evaluate(self, tests: list[PersonalizationTest], **kwargs) -> MetricResult:
        test_results = []

        for test in tests:
            persona_outcomes = []

            for persona in test.personas:
                scored = build_scored_products(test.products, persona.rubric_weights)
                rank1 = scored[0]["name"] if scored else ""
                top3 = rank_names(scored)[:3]

                persona_outcomes.append({
                    "persona_id": persona.persona_id,
                    "persona_name": persona.persona_name,
                    "rank1": rank1,
                    "expected_rank1": persona.expected_rank_1,
                    "top3": top3,
                    "rank1_correct": rank1 == persona.expected_rank_1,
                })

            # Diversity: how many distinct rank-1 winners?
            distinct_rank1 = len({p["rank1"] for p in persona_outcomes})
            required_diversity = test.min_rank_1_diversity
            diversity_ratio = min(distinct_rank1 / max(required_diversity, 1), 1.0)

            # Accuracy: how many personas got the right rank-1?
            accuracy = sum(1 for p in persona_outcomes if p["rank1_correct"]) / max(len(persona_outcomes), 1)

            # Combined score: 50% diversity, 50% accuracy
            test_score = (diversity_ratio * 0.5 + accuracy * 0.5) * 100

            passed = distinct_rank1 >= required_diversity and accuracy >= 0.5

            test_results.append({
                "id": test.id,
                "name": test.name,
                "score": round(test_score, 1),
                "passed": passed,
                "distinct_rank1": distinct_rank1,
                "required_diversity": required_diversity,
                "persona_accuracy": round(accuracy * 100, 1),
                "personas": persona_outcomes,
            })

        score = (sum(t["score"] for t in test_results) / len(test_results)) if test_results else 0.0
        threshold = PASS_THRESHOLDS[self.name]

        failures = []
        for t in test_results:
            if not t["passed"]:
                if t["distinct_rank1"] < t["required_diversity"]:
                    failures.append(
                        f"[{t['id']}] only {t['distinct_rank1']} distinct winners, "
                        f"expected >={t['required_diversity']}"
                    )
                for p in t["personas"]:
                    if not p["rank1_correct"]:
                        failures.append(
                            f"[{t['id']}:{p['persona_id']}] got '{p['rank1']}', "
                            f"expected '{p['expected_rank1']}'"
                        )

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_tests": len(test_results),
                "passed": sum(1 for t in test_results if t["passed"]),
                "tests": test_results,
            },
            failures=failures[:20],
        )
