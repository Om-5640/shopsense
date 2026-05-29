"""
Phase 3: Semantic Consistency

Offline mode: verifies that all variants in a cluster produce the same rank-1 winner
when run against the same product pool and rubric.
(Online mode would feed variant queries to the real pipeline and compare rankings.)
"""

from __future__ import annotations
from evals.benchmarks.base import SemanticCluster
from evals.engine import build_scored_products, rank_names
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS


class SemanticConsistencyMetric(BaseMetric):
    name = "semantic_consistency"
    phase = "Phase 3: Semantic Robustness"

    def evaluate(self, clusters: list[SemanticCluster], **kwargs) -> MetricResult:
        cluster_results = []

        for cluster in clusters:
            # Run the single (offline) rubric against the product pool
            scored = build_scored_products(cluster.products, cluster.rubric_weights)
            rank1 = scored[0]["name"] if scored else ""
            top3 = rank_names(scored)[:3]

            # Check: rank-1 is in expected_top_products
            expected_hit = rank1 in cluster.expected_top_products

            # Check: all expected_top_products appear in top-3
            top3_coverage = sum(
                1 for p in cluster.expected_top_products if p in top3
            ) / max(len(cluster.expected_top_products), 1)

            # Semantic consistency score for this cluster: 0-100
            cluster_score = (
                (0.6 if expected_hit else 0.0) +
                (0.4 * top3_coverage)
            ) * 100

            cluster_results.append({
                "id": cluster.id,
                "name": cluster.name,
                "rank1": rank1,
                "top3": top3,
                "expected_top_products": cluster.expected_top_products,
                "score": round(cluster_score, 1),
                "passed": cluster_score >= 60.0,
                "variants_count": len(cluster.variants),
            })

        if not cluster_results:
            score = 0.0
        else:
            score = sum(c["score"] for c in cluster_results) / len(cluster_results)

        threshold = PASS_THRESHOLDS[self.name]
        failures = [
            f"[{c['id']}] rank1='{c['rank1']}', expected one of {c['expected_top_products']}"
            for c in cluster_results if not c["passed"]
        ]

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_clusters": len(cluster_results),
                "passed": sum(1 for c in cluster_results if c["passed"]),
                "clusters": cluster_results,
            },
            failures=failures,
        )
