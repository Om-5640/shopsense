"""
Phase 14: Mention Popularity Bias

Verifies that the scoring engine is immune to mention-count manipulation —
changing mention_count, positive_mentions, or negative_mentions on any product
must not affect its weighted_total or ranking.

Three checks per scenario (weights: 50 / 30 / 20):
  1. score_invariant (50 pts) — weighted_total is bit-identical between baseline
                                 and biased products for every product in the pool
  2. rank1_stable    (30 pts) — rank-1 winner is the same product in both variants
  3. top3_stable     (20 pts) — full top-3 name order is identical in both variants

Score = average per-scenario score across all 10 scenarios.
All checks are deterministic pure-Python arithmetic — zero LLM calls.
"""

from __future__ import annotations

from evals.benchmarks.mention_popularity_bias import BiasScenario
from evals.engine import build_scored_products
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


def _rank1(products, rubric) -> str:
    ranked = build_scored_products(products, rubric)
    return ranked[0]["name"] if ranked else ""


def _top3(products, rubric) -> list[str]:
    ranked = build_scored_products(products, rubric)
    return [r["name"] for r in ranked[:3]]


def _weighted_totals(products, rubric) -> dict[str, float]:
    """Return {product_name: weighted_total} for all products under rubric."""
    ranked = build_scored_products(products, rubric)
    return {r["name"]: r["weighted_total"] for r in ranked}


class MentionPopularityBiasMetric(BaseMetric):
    name = "mention_popularity_bias"
    phase = "Phase 14: Mention Popularity Bias"

    def evaluate(
        self,
        scenarios: list[BiasScenario],
        **kwargs,
    ) -> MetricResult:
        threshold = PASS_THRESHOLDS.get(self.name, 85.0)

        if not scenarios:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="no bias scenarios provided",
            )

        failures: list[str] = []
        scenario_details: list[dict] = []
        per_scores: list[float] = []

        for sc in scenarios:
            # ── Check 1 (50 pts): weighted_totals identical between baseline and biased
            baseline_totals = _weighted_totals(sc.baseline_products, sc.rubric_weights)
            biased_totals = _weighted_totals(sc.biased_products, sc.rubric_weights)
            invariant_failures: list[str] = []
            for name in baseline_totals:
                b = baseline_totals[name]
                m = biased_totals.get(name, -1.0)
                if b != m:
                    invariant_failures.append(
                        f"{name}: baseline={b}, biased={m}"
                    )
            score_invariant = len(invariant_failures) == 0

            # ── Check 2 (30 pts): rank-1 unchanged
            baseline_rank1 = _rank1(sc.baseline_products, sc.rubric_weights)
            biased_rank1 = _rank1(sc.biased_products, sc.rubric_weights)
            rank1_stable = biased_rank1 == sc.expected_rank_1

            # ── Check 3 (20 pts): top-3 unchanged
            baseline_top3 = _top3(sc.baseline_products, sc.rubric_weights)
            biased_top3 = _top3(sc.biased_products, sc.rubric_weights)
            top3_stable = biased_top3 == sc.expected_top_3

            per_score = (
                (1.0 if score_invariant else 0.0) * 0.50
                + (1.0 if rank1_stable else 0.0) * 0.30
                + (1.0 if top3_stable else 0.0) * 0.20
            ) * 100.0

            per_scores.append(per_score)

            if not score_invariant:
                for msg in invariant_failures:
                    failures.append(
                        f"[{sc.id}] score_invariant FAIL — weighted_total changed: {msg}"
                    )
            if not rank1_stable:
                failures.append(
                    f"[{sc.id}] rank1_stable FAIL — expected '{sc.expected_rank_1}', "
                    f"biased produced '{biased_rank1}'"
                )
            if not top3_stable:
                failures.append(
                    f"[{sc.id}] top3_stable FAIL — expected {sc.expected_top_3}, "
                    f"biased produced {biased_top3}"
                )

            scenario_details.append({
                "id": sc.id,
                "name": sc.name,
                "bias_type": sc.bias_type,
                "per_score": round(per_score, 1),
                "score_invariant": score_invariant,
                "rank1_stable": rank1_stable,
                "top3_stable": top3_stable,
                "baseline_rank1": baseline_rank1,
                "biased_rank1": biased_rank1,
                "expected_rank_1": sc.expected_rank_1,
                "baseline_top3": baseline_top3,
                "biased_top3": biased_top3,
                "expected_top_3": sc.expected_top_3,
                "invariant_failures": invariant_failures,
                "tags": sc.tags,
            })

        score = round(sum(per_scores) / len(per_scores), 1)

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": len(scenarios),
                "score_invariant_passes": sum(1 for d in scenario_details if d["score_invariant"]),
                "rank1_stable_passes": sum(1 for d in scenario_details if d["rank1_stable"]),
                "top3_stable_passes": sum(1 for d in scenario_details if d["top3_stable"]),
                "scenarios": scenario_details,
            },
            failures=failures,
        )
