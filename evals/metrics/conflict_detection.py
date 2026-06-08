"""
Phase 13: Conflict Detection

Evaluates the scoring engine's behaviour under rubric conflicts — cases where
two criteria a user cares about equally point to different specialist products.

Three checks per scenario (weights: 40 / 30 / 30):
  1. rank_correct   (40 pts) — balanced rubric picks the expected_balanced_winner
  2. primary_wins   (30 pts) — extreme single-criterion rubric (primary) picks primary_champion
  3. secondary_wins (30 pts) — extreme single-criterion rubric (secondary) picks secondary_champion

Score = average per-scenario score across all 10 scenarios.
All checks are deterministic pure-Python arithmetic — zero LLM calls.
"""

from __future__ import annotations

from evals.benchmarks.conflict_detection import ConflictScenario
from evals.benchmarks.base import RubricWeight
from evals.engine import build_scored_products
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


def _extreme_rubric(rubric: list[RubricWeight], dominant: str) -> list[RubricWeight]:
    """Return a copy of `rubric` with 10.0 on `dominant` and 0.0 on all others."""
    return [
        RubricWeight(rw.criterion, rw.label, 10.0 if rw.criterion == dominant else 0.0)
        for rw in rubric
    ]


def _top_name(products, rubric: list[RubricWeight]) -> str:
    """Return the name of the top-ranked product under `rubric`."""
    ranked = build_scored_products(products, rubric)
    return ranked[0]["name"] if ranked else ""


class ConflictDetectionMetric(BaseMetric):
    name = "conflict_detection"
    phase = "Phase 13: Conflict Detection"

    def evaluate(
        self,
        scenarios: list[ConflictScenario],
        **kwargs,
    ) -> MetricResult:
        threshold = PASS_THRESHOLDS.get(self.name, 80.0)

        if not scenarios:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="no conflict scenarios provided",
            )

        failures: list[str] = []
        scenario_details: list[dict] = []
        per_scores: list[float] = []

        for sc in scenarios:
            # Check 1 — balanced rubric
            balanced_winner = _top_name(sc.products, sc.rubric_weights)
            rank_correct = balanced_winner == sc.expected_balanced_winner

            # Check 2 — primary criterion extreme
            primary_rubric = _extreme_rubric(sc.rubric_weights, sc.primary_criterion)
            primary_winner = _top_name(sc.products, primary_rubric)
            primary_wins = primary_winner == sc.primary_champion

            # Check 3 — secondary criterion extreme
            secondary_rubric = _extreme_rubric(sc.rubric_weights, sc.secondary_criterion)
            secondary_winner = _top_name(sc.products, secondary_rubric)
            secondary_wins = secondary_winner == sc.secondary_champion

            per_score = (
                (1.0 if rank_correct else 0.0) * 0.40
                + (1.0 if primary_wins else 0.0) * 0.30
                + (1.0 if secondary_wins else 0.0) * 0.30
            ) * 100.0

            per_scores.append(per_score)

            if not rank_correct:
                failures.append(
                    f"[{sc.id}] balanced winner: expected '{sc.expected_balanced_winner}', "
                    f"got '{balanced_winner}'"
                )
            if not primary_wins:
                failures.append(
                    f"[{sc.id}] primary champion ({sc.primary_criterion}): "
                    f"expected '{sc.primary_champion}', got '{primary_winner}'"
                )
            if not secondary_wins:
                failures.append(
                    f"[{sc.id}] secondary champion ({sc.secondary_criterion}): "
                    f"expected '{sc.secondary_champion}', got '{secondary_winner}'"
                )

            scenario_details.append({
                "id": sc.id,
                "name": sc.name,
                "per_score": round(per_score, 1),
                "rank_correct": rank_correct,
                "primary_wins": primary_wins,
                "secondary_wins": secondary_wins,
                "balanced_winner": balanced_winner,
                "expected_balanced_winner": sc.expected_balanced_winner,
                "primary_winner": primary_winner,
                "primary_champion": sc.primary_champion,
                "secondary_winner": secondary_winner,
                "secondary_champion": sc.secondary_champion,
                "genuine_conflict": sc.genuine_conflict,
                "tags": sc.tags,
            })

        score = round(sum(per_scores) / len(per_scores), 1)
        all_passed = len(failures) == 0

        genuine_count = sum(1 for sc in scenarios if sc.genuine_conflict)
        rank_correct_count = sum(1 for d in scenario_details if d["rank_correct"])
        primary_wins_count = sum(1 for d in scenario_details if d["primary_wins"])
        secondary_wins_count = sum(1 for d in scenario_details if d["secondary_wins"])

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": len(scenarios),
                "genuine_conflict_scenarios": genuine_count,
                "rank_correct": rank_correct_count,
                "primary_wins": primary_wins_count,
                "secondary_wins": secondary_wins_count,
                "scenarios": scenario_details,
            },
            failures=failures,
        )
