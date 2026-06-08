"""
Phase 15: Nugget-Based Partial Credit for Human Alignment.

Instead of a binary top-3 match, each judgment is evaluated through a set of
*nuggets* — explicit insight claims listing which products they mention.  Credit
is awarded proportionally based on whether the engine agrees with the expert
about which products belong in the top-3.

Credit formula per nugget:
    For each product P in nugget.products_mentioned:
      P in expert_top3 and P in engine_top3     → 1.0  (both agree: include)
      P not in expert_top3, not in engine_top3  → 1.0  (both agree: exclude)
      P in expert_top3, not in engine_top3      → 0.0  (engine misses expert pick)
      P not in expert_top3, P in engine_top3    → 0.5  (engine over-includes)
    nugget_credit = mean of per-product credits
    Empty products_mentioned                    → 0.8  (generic insight: neutral)

Per-judgment score  = mean(nugget_credits) × 100
Overall metric score = mean(per-judgment scores)

All arithmetic is pure Python — zero LLM calls.
"""

from __future__ import annotations

from evals.benchmarks.nugget_alignment import Nugget, NuggetJudgment
from evals.engine import build_scored_products
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


def _engine_top3(judgment: NuggetJudgment) -> set[str]:
    """Run the scoring engine and return the top-3 product names as a set."""
    ranked = build_scored_products(judgment.products, judgment.rubric_weights)
    return {r["name"] for r in ranked[:3]}


def _nugget_credit(
    products_mentioned: list[str],
    expert_top3: set[str],
    engine_top3: set[str],
) -> float:
    """
    Compute partial credit for a single nugget.

    Returns 0.8 for empty product lists (generic insight, no products to compare).
    """
    if not products_mentioned:
        return 0.8

    credits: list[float] = []
    for product in products_mentioned:
        in_expert = product in expert_top3
        in_engine = product in engine_top3
        if in_expert and in_engine:
            credits.append(1.0)
        elif not in_expert and not in_engine:
            credits.append(1.0)
        elif in_expert and not in_engine:
            credits.append(0.0)
        else:
            credits.append(0.5)

    return sum(credits) / len(credits)


class NuggetAlignmentMetric(BaseMetric):
    name = "nugget_alignment"
    phase = "Phase 15: Nugget-Based Partial Credit"

    def evaluate(
        self,
        judgments: list[NuggetJudgment],
        **kwargs,
    ) -> MetricResult:
        threshold = PASS_THRESHOLDS.get(self.name, 70.0)

        if not judgments:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="no nugget judgments provided",
            )

        failures: list[str] = []
        judgment_details: list[dict] = []
        per_scores: list[float] = []

        for jdg in judgments:
            expert_top3 = jdg.expert_top3
            engine_top3 = _engine_top3(jdg)

            nugget_credits: list[float] = []
            nugget_detail: list[dict] = []

            for nugget in jdg.nuggets:
                credit = _nugget_credit(
                    nugget.products_mentioned,
                    expert_top3,
                    engine_top3,
                )
                nugget_credits.append(credit)
                nugget_detail.append({
                    "text": nugget.text[:80],
                    "products_mentioned": nugget.products_mentioned,
                    "credit": round(credit, 3),
                })

            if nugget_credits:
                judgment_score = (sum(nugget_credits) / len(nugget_credits)) * 100.0
            else:
                judgment_score = 0.0

            per_scores.append(judgment_score)

            if judgment_score < 70.0:
                failures.append(
                    f"[{jdg.id}] nugget_alignment={round(judgment_score, 1):.1f} "
                    f"(expert_top3={sorted(expert_top3)}, engine_top3={sorted(engine_top3)})"
                )

            judgment_details.append({
                "id": jdg.id,
                "name": jdg.name,
                "n_nuggets": jdg.n_nuggets,
                "expert_top3": sorted(expert_top3),
                "engine_top3": sorted(engine_top3),
                "judgment_score": round(judgment_score, 1),
                "nuggets": nugget_detail,
            })

        score = round(sum(per_scores) / len(per_scores), 1)

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_judgments": len(judgments),
                "full_credit_judgments": sum(
                    1 for d in judgment_details if d["judgment_score"] >= 99.9
                ),
                "partial_credit_judgments": sum(
                    1 for d in judgment_details
                    if 0.1 < d["judgment_score"] < 99.9
                ),
                "judgment_details": judgment_details,
            },
            failures=failures,
        )
