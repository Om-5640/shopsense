"""
Phase 7: Ranking Quality

Evaluates whether the ranking is internally consistent:
- Products with higher scores appear above products with lower scores
- The weighted_total correctly reflects rubric priorities
- Top-k relevance: top-3 products have strong signal
- Score spread: there's meaningful differentiation between products
"""

from __future__ import annotations
from evals.benchmarks.base import OfflineScenario, HumanJudgment
from evals.engine import build_scored_products, rank_names, rank_of
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class RankingQualityMetric(BaseMetric):
    name = "ranking_quality"
    phase = "Phase 7: Ranking Quality"

    def evaluate(self, scenarios: list[OfflineScenario], **kwargs) -> MetricResult:
        results = []

        for s in scenarios:
            scored = build_scored_products(s.products, s.rubric_weights)
            issues = []

            # Check 1: ranking is consistent (sorted by weighted_total)
            totals = [p["weighted_total"] for p in scored]
            if totals != sorted(totals, reverse=True):
                issues.append("ranking_inconsistency: products not sorted by weighted_total")

            # Check 2: no negative scores
            for p in scored:
                if p["weighted_total"] < 0:
                    issues.append(f"{p['name']}: negative weighted_total {p['weighted_total']}")

            # Check 3: percentages are valid (0-100)
            for p in scored:
                if not (0 <= p["percentage"] <= 100.01):
                    issues.append(f"{p['name']}: invalid percentage {p['percentage']}")

            # Check 4: max_possible > 0
            for p in scored:
                if p["max_possible"] <= 0:
                    issues.append(f"{p['name']}: max_possible={p['max_possible']}")

            # Check 5: score spread (top product should have higher score than bottom)
            if len(scored) >= 2:
                spread = scored[0]["percentage"] - scored[-1]["percentage"]
                if spread < 5.0:
                    issues.append(f"low_spread: only {round(spread, 1)}% between rank-1 and last")

            # Check 6: top product actually satisfies the user's primary criterion
            if s.rubric_weights:
                top_criterion = max(s.rubric_weights, key=lambda r: r.weight)
                rank1_product = scored[0] if scored else None
                if rank1_product:
                    rank1_top_score = next(
                        (sc["score"] for sc in rank1_product["scores"]
                         if sc["criterion"] == top_criterion.criterion),
                        None
                    )
                    if rank1_top_score is not None and rank1_top_score < 4:
                        issues.append(
                            f"rank1_fails_top_criterion: '{rank1_product['name']}' scores "
                            f"{rank1_top_score}/10 on top criterion '{top_criterion.criterion}'"
                        )

            passed = len(issues) == 0
            results.append({
                "scenario_id": s.id,
                "passed": passed,
                "issues": issues,
                "spread": round(
                    scored[0]["percentage"] - scored[-1]["percentage"], 1
                ) if len(scored) >= 2 else 0.0,
            })

        passing = [r for r in results if r["passed"]]
        score = (len(passing) / len(results) * 100) if results else 0.0
        threshold = PASS_THRESHOLDS[self.name]

        avg_spread = sum(r["spread"] for r in results) / max(len(results), 1)
        failures = [
            f"[{r['scenario_id']}] {i}"
            for r in results if not r["passed"]
            for i in r["issues"]
        ]

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": len(results),
                "passed": len(passing),
                "avg_score_spread": round(avg_spread, 1),
            },
            failures=failures[:20],
        )


class GoldRankingQualityMetric(BaseMetric):
    """Compares against expert (human judgment) gold rankings."""
    name = "ranking_quality"
    phase = "Phase 7: Gold Ranking Quality"

    def evaluate(self, human_judgments: list[HumanJudgment], **kwargs) -> MetricResult:
        results = []

        for hj in human_judgments:
            scored = build_scored_products(hj.products, hj.rubric_weights)
            ranks = rank_names(scored)
            top3 = ranks[:3]

            # Rank-1 match
            rank1_hit = (ranks[0] if ranks else "") == hj.expert_rank_1

            # Top-3 coverage
            expert_top3 = [hj.expert_rank_1, hj.expert_rank_2, hj.expert_rank_3]
            top3_hits = sum(1 for e in expert_top3 if e in top3)

            # NDCG-style scoring
            ndcg = _ndcg3(ranks, expert_top3)

            scenario_score = ndcg * 100
            issues = []
            if not rank1_hit:
                issues.append(
                    f"rank1: got '{ranks[0] if ranks else ''}', expert says '{hj.expert_rank_1}'"
                )
            if top3_hits < 2:
                issues.append(f"only {top3_hits}/3 expert top products in our top 3")

            results.append({
                "id": hj.id,
                "name": hj.name,
                "our_top3": top3,
                "expert_top3": expert_top3,
                "rank1_hit": rank1_hit,
                "top3_hits": top3_hits,
                "ndcg": round(ndcg, 3),
                "score": round(scenario_score, 1),
                "passed": scenario_score >= 60.0,
                "issues": issues,
            })

        score = sum(r["score"] for r in results) / max(len(results), 1)
        threshold = PASS_THRESHOLDS[self.name]
        failures = [f"[{r['id']}] {i}" for r in results if r["issues"] for i in r["issues"]]

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total": len(results),
                "passed": sum(1 for r in results if r["passed"]),
                "avg_ndcg": round(sum(r["ndcg"] for r in results) / max(len(results), 1), 3),
                "scenarios": results,
            },
            failures=failures[:20],
        )


def _ndcg3(our_ranks: list[str], gold: list[str]) -> float:
    """Compute NDCG@3 — normalised discounted cumulative gain at position 3."""
    import math
    def dcg(ranks: list[str], rel_map: dict[str, float]) -> float:
        return sum(
            rel_map.get(item, 0) / math.log2(i + 2)
            for i, item in enumerate(ranks[:3])
        )
    rel = {gold[0]: 3.0, gold[1]: 2.0, gold[2]: 1.0}
    ideal_dcg = dcg(gold, rel)
    actual_dcg = dcg(our_ranks, rel)
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0
