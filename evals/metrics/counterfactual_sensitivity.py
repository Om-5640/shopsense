"""
Phase 5: Counterfactual Sensitivity

For each counterfactual pair: run base rubric and modified rubric (one criterion changed).
Verify the ranking changes in the expected direction.
If the ranking NEVER changes when a single criterion is modified, the system is insensitive.
"""

from __future__ import annotations
from evals.benchmarks.base import CounterfactualPair
from evals.engine import build_scored_products, rank_names
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class CounterfactualSensitivityMetric(BaseMetric):
    name = "counterfactual_sensitivity"
    phase = "Phase 5: Counterfactual Evals"

    def evaluate(self, pairs: list[CounterfactualPair], **kwargs) -> MetricResult:
        pair_results = []

        for pair in pairs:
            base_scored = build_scored_products(pair.products, pair.base_rubric)
            mod_scored = build_scored_products(pair.products, pair.modified_rubric)

            base_rank1 = base_scored[0]["name"] if base_scored else ""
            mod_rank1 = mod_scored[0]["name"] if mod_scored else ""

            base_ranks = rank_names(base_scored)
            mod_ranks = rank_names(mod_scored)

            # Did ranking change?
            ranking_changed = base_rank1 != mod_rank1

            # Did the base winner match expectation?
            base_winner_correct = base_rank1 == pair.base_winner

            # Did the modified winner match expectation?
            mod_winner_correct = mod_rank1 == pair.modified_winner

            # Kendall tau distance between two rankings (normalised 0-1)
            tau = _kendall_tau_distance(base_ranks, mod_ranks)

            failures = []
            if not base_winner_correct:
                failures.append(
                    f"base_winner: got '{base_rank1}', expected '{pair.base_winner}'"
                )
            if not mod_winner_correct:
                failures.append(
                    f"modified_winner: got '{mod_rank1}', expected '{pair.modified_winner}'"
                )
            if pair.must_differ and not ranking_changed:
                failures.append(
                    f"ranking_unchanged after modifying '{pair.changed_criterion}'"
                )

            passed = len(failures) == 0
            # Score: full credit if both winners correct + ranking changed; partial otherwise
            if passed:
                pair_score = 100.0
            elif base_winner_correct or mod_winner_correct:
                pair_score = 50.0
            else:
                pair_score = 0.0

            pair_results.append({
                "id": pair.id,
                "name": pair.name,
                "changed_criterion": pair.changed_criterion,
                "base_winner": base_rank1,
                "modified_winner": mod_rank1,
                "ranking_changed": ranking_changed,
                "kendall_tau": round(tau, 3),
                "score": pair_score,
                "passed": passed,
                "failures": failures,
            })

        score = (sum(p["score"] for p in pair_results) / len(pair_results)) if pair_results else 0.0
        threshold = PASS_THRESHOLDS[self.name]

        failures_list = [
            f"[{p['id']}] {f}"
            for p in pair_results if not p["passed"]
            for f in p["failures"]
        ]

        # Sensitivity spread: which criteria don't trigger ranking changes?
        insensitive = [
            p["changed_criterion"]
            for p in pair_results
            if p.get("ranking_unchanged", False) or not p["ranking_changed"]
        ]

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_pairs": len(pair_results),
                "passed": sum(1 for p in pair_results if p["passed"]),
                "insensitive_criteria": list(set(insensitive)),
                "avg_kendall_tau": round(
                    sum(p["kendall_tau"] for p in pair_results) / max(len(pair_results), 1), 3
                ),
                "pairs": pair_results,
            },
            failures=failures_list[:20],
        )


def _kendall_tau_distance(rank_a: list[str], rank_b: list[str]) -> float:
    """Normalised Kendall tau distance between two ranked lists. 0=identical, 1=reversed."""
    items = [x for x in rank_a if x in rank_b]
    n = len(items)
    if n < 2:
        return 0.0
    pos_b = {item: i for i, item in enumerate(rank_b)}
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a_order = items.index(items[i]) < items.index(items[j])
            b_order = pos_b.get(items[i], 0) < pos_b.get(items[j], 0)
            if a_order == b_order:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return discordant / total if total > 0 else 0.0
