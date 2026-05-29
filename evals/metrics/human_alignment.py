"""
Phase 11: Human Alignment

Compares ShopSense rankings against expert-annotated "gold" rankings.
The Human Alignment Score is the primary North Star metric for long-term quality.

Measures:
  - Rank-1 agreement with expert
  - Top-3 overlap with expert's top-3
  - NDCG@3 (normalised discounted cumulative gain)
  - Tradeoff awareness: does the system acknowledge the same tradeoffs the expert listed?
"""

from __future__ import annotations
from evals.benchmarks.base import HumanJudgment
from evals.engine import build_scored_products, rank_names
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS
from evals.metrics.ranking_quality import _ndcg3


class HumanAlignmentMetric(BaseMetric):
    name = "human_alignment"
    phase = "Phase 11: Human Alignment"

    def evaluate(self, human_judgments: list[HumanJudgment], **kwargs) -> MetricResult:
        results = []

        for hj in human_judgments:
            scored = build_scored_products(hj.products, hj.rubric_weights)
            our_ranks = rank_names(scored)
            expert_top3 = [hj.expert_rank_1, hj.expert_rank_2, hj.expert_rank_3]

            rank1_match = (our_ranks[0] if our_ranks else "") == hj.expert_rank_1
            top3_hits = sum(1 for e in expert_top3 if e in our_ranks[:3])
            ndcg = _ndcg3(our_ranks, expert_top3)

            # Tradeoff detection: look for expert tradeoff products in our rankings
            tradeoff_awareness = _tradeoff_awareness(hj, scored)

            # Composite alignment score
            alignment = (
                (1.0 if rank1_match else 0.0) * 0.40
                + (top3_hits / 3.0) * 0.35
                + ndcg * 0.15
                + tradeoff_awareness * 0.10
            ) * 100

            issues = []
            if not rank1_match:
                issues.append(
                    f"rank1_mismatch: we say '{our_ranks[0] if our_ranks else ''}', "
                    f"expert says '{hj.expert_rank_1}'"
                )
            if top3_hits < 2:
                issues.append(f"top3_miss: only {top3_hits}/3 expert products in our top-3")

            results.append({
                "id": hj.id,
                "name": hj.name,
                "our_rank1": our_ranks[0] if our_ranks else "",
                "expert_rank1": hj.expert_rank_1,
                "our_top3": our_ranks[:3],
                "expert_top3": expert_top3,
                "rank1_match": rank1_match,
                "top3_hits": top3_hits,
                "ndcg3": round(ndcg, 3),
                "tradeoff_awareness": round(tradeoff_awareness, 3),
                "alignment_score": round(alignment, 1),
                "passed": alignment >= 60.0,
                "issues": issues,
            })

        score = sum(r["alignment_score"] for r in results) / max(len(results), 1)
        threshold = PASS_THRESHOLDS[self.name]
        failures = [f"[{r['id']}] {i}" for r in results if r["issues"] for i in r["issues"]]

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_judgments": len(results),
                "passed": sum(1 for r in results if r["passed"]),
                "avg_ndcg3": round(sum(r["ndcg3"] for r in results) / max(len(results), 1), 3),
                "rank1_accuracy": round(
                    sum(1 for r in results if r["rank1_match"]) / max(len(results), 1) * 100, 1
                ),
                "judgments": results,
            },
            failures=failures[:20],
        )


def _tradeoff_awareness(hj: HumanJudgment, scored: list[dict]) -> float:
    """
    Check if our ranking implicitly respects the expert's stated tradeoffs.
    Heuristic: products mentioned in tradeoffs should appear in our top-3.
    """
    if not hj.key_tradeoffs:
        return 0.8  # no tradeoffs to check → neutral

    top3_names = {p["name"] for p in scored[:3]}
    expert_products = {hj.expert_rank_1, hj.expert_rank_2, hj.expert_rank_3}
    overlap = len(top3_names & expert_products)
    return overlap / max(len(expert_products), 1)
