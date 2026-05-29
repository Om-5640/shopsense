"""
Phase 12: Tournament Evaluation System

Compare a "candidate" system (different rubric weights, scoring logic, or config)
against the "production" baseline across all benchmark scenarios.

Usage:
    python -m evals tournament --candidate-config path/to/candidate_config.json

Future architecture changes must beat production here before deployment.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from evals.benchmarks import all_scenarios, all_personalization_tests, all_counterfactuals
from evals.benchmarks.base import OfflineScenario
from evals.engine import build_scored_products, rank_of
from evals.metrics import (
    RecommendationQualityMetric,
    PersonalizationStrengthMetric,
    CounterfactualSensitivityMetric,
    RankingQualityMetric,
    RobustnessMetric,
)
from evals.metrics.base import MetricResult
from evals.index import compute_index
from evals.benchmarks import all_adversarial


@dataclass
class TournamentResult:
    production_index: float
    candidate_index: float
    winner: str   # "production" | "candidate" | "tie"
    delta: float

    production_scores: dict[str, float] = field(default_factory=dict)
    candidate_scores: dict[str, float] = field(default_factory=dict)

    head_to_head: dict[str, str] = field(default_factory=dict)  # metric → winner
    wins: dict[str, int] = field(default_factory=dict)
    ties: int = 0
    recommendation: str = ""

    scenario_results: list[dict] = field(default_factory=list)


class Tournament:
    """
    Runs all benchmark scenarios against two scoring configurations,
    then compares overall quality.

    In the current implementation both systems use the same offline scoring engine
    but accept different rubric weight modifiers to simulate different system behaviour.
    """

    def __init__(
        self,
        production_weight_multipliers: dict[str, float] | None = None,
        candidate_weight_multipliers: dict[str, float] | None = None,
    ):
        """
        weight_multipliers: {criterion_name: multiplier} applied to each scenario's rubric.
        E.g. {"noise_cancellation": 1.5} amplifies ANC weight by 50% across all scenarios.
        None = production baseline (no modification).
        """
        self.prod_mults = production_weight_multipliers or {}
        self.cand_mults = candidate_weight_multipliers or {}

        self.scenarios = all_scenarios()
        self.personalization_tests = all_personalization_tests()
        self.counterfactuals = all_counterfactuals()
        self.adversarial = all_adversarial()

    def run(self) -> TournamentResult:
        print("\n── Tournament Evaluation ──────────────────────────────────")
        print(f"   Production: {self.prod_mults or 'baseline'}")
        print(f"   Candidate:  {self.cand_mults or 'baseline'}")
        print("──────────────────────────────────────────────────────────\n")

        prod_scenarios = self._apply_multipliers(self.scenarios, self.prod_mults)
        cand_scenarios = self._apply_multipliers(self.scenarios, self.cand_mults)

        prod_metrics: dict[str, MetricResult] = {}
        cand_metrics: dict[str, MetricResult] = {}

        for MetricClass in [
            RecommendationQualityMetric,
            RankingQualityMetric,
        ]:
            m = MetricClass()
            prod_metrics[m.name] = m.evaluate(prod_scenarios)
            cand_metrics[m.name] = m.evaluate(cand_scenarios)

        # Personalization
        m = PersonalizationStrengthMetric()
        prod_metrics[m.name] = m.evaluate(self.personalization_tests)
        cand_metrics[m.name] = m.evaluate(self.personalization_tests)

        # Counterfactual
        m = CounterfactualSensitivityMetric()
        prod_metrics[m.name] = m.evaluate(self.counterfactuals)
        cand_metrics[m.name] = m.evaluate(self.counterfactuals)

        # Robustness
        m = RobustnessMetric()
        prod_metrics[m.name] = m.evaluate(self.adversarial)
        cand_metrics[m.name] = m.evaluate(self.adversarial)

        prod_index = compute_index(prod_metrics)
        cand_index = compute_index(cand_metrics)

        # Head-to-head per metric
        head_to_head: dict[str, str] = {}
        wins = {"production": 0, "candidate": 0}
        ties = 0
        for metric in prod_metrics:
            p = prod_metrics[metric].score
            c = cand_metrics[metric].score
            if abs(p - c) < 0.5:
                head_to_head[metric] = "tie"
                ties += 1
            elif p > c:
                head_to_head[metric] = "production"
                wins["production"] += 1
            else:
                head_to_head[metric] = "candidate"
                wins["candidate"] += 1

        delta = cand_index - prod_index
        if abs(delta) < 0.5:
            winner = "tie"
        elif delta > 0:
            winner = "candidate"
        else:
            winner = "production"

        recommendation = _make_recommendation(winner, delta, head_to_head)

        result = TournamentResult(
            production_index=prod_index,
            candidate_index=cand_index,
            winner=winner,
            delta=round(delta, 1),
            production_scores={k: v.score for k, v in prod_metrics.items()},
            candidate_scores={k: v.score for k, v in cand_metrics.items()},
            head_to_head=head_to_head,
            wins=wins,
            ties=ties,
            recommendation=recommendation,
        )

        _print_tournament_result(result)
        return result

    def _apply_multipliers(
        self,
        scenarios: list[OfflineScenario],
        mults: dict[str, float],
    ) -> list[OfflineScenario]:
        if not mults:
            return scenarios
        import copy
        modified = []
        for s in scenarios:
            s2 = copy.deepcopy(s)
            for rw in s2.rubric_weights:
                if rw.criterion in mults:
                    rw.weight = min(10.0, rw.weight * mults[rw.criterion])
            modified.append(s2)
        return modified


def _make_recommendation(winner: str, delta: float, head_to_head: dict) -> str:
    if winner == "candidate" and delta >= 2.0:
        return f"RECOMMEND MERGE — candidate improves Intelligence Index by {delta:+.1f} points"
    if winner == "production":
        return f"BLOCK MERGE — candidate regresses Intelligence Index by {abs(delta):.1f} points"
    regression_metrics = [m for m, w in head_to_head.items() if w == "production"]
    if winner == "candidate" and regression_metrics:
        return (
            f"CONDITIONAL — candidate wins overall (+{delta:.1f}) but regresses: "
            f"{', '.join(regression_metrics)}"
        )
    return "NEUTRAL — no significant difference"


def _print_tournament_result(result: TournamentResult) -> None:
    print(f"\n{'='*60}")
    print(f"  TOURNAMENT RESULT")
    print(f"{'='*60}")
    print(f"  Production Index:  {result.production_index:.1f}")
    print(f"  Candidate Index:   {result.candidate_index:.1f}")
    print(f"  Delta:             {result.delta:+.1f}")
    print(f"  Winner:            {result.winner.upper()}")
    print(f"\n  Head-to-head:")
    for metric, winner in result.head_to_head.items():
        p = result.production_scores.get(metric, 0)
        c = result.candidate_scores.get(metric, 0)
        marker = "→ CAND" if winner == "candidate" else ("← PROD" if winner == "production" else "  TIE ")
        print(f"    {marker}  {metric}: {p:.1f} vs {c:.1f}")
    print(f"\n  ▶ {result.recommendation}")
    print(f"{'='*60}\n")
