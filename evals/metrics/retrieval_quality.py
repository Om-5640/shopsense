"""
Phase 6: Retrieval Quality

Evaluates whether retrieved research evidence covers:
- Strengths (praise fields populated)
- Weaknesses (complaints fields populated)
- Community signal (mention_count > threshold)
- Source diversity (multiple subreddits/sources cited)
- Experiential evidence (first-person usage mentions)

Offline mode evaluates the synthetic benchmark product profiles.
Online mode evaluates results from real pipeline runs.
"""

from __future__ import annotations
from evals.benchmarks.base import OfflineScenario
from evals.engine import build_scored_products
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS

# Minimum thresholds for a "healthy" product evidence profile
MIN_MENTIONS = 10
MIN_PRAISE_COUNT = 1
MIN_COMPLAINT_COUNT = 1
MIN_SOURCES = 1


class RetrievalQualityMetric(BaseMetric):
    name = "retrieval_quality"
    phase = "Phase 6: Retrieval Quality"

    def evaluate(self, scenarios: list[OfflineScenario], **kwargs) -> MetricResult:
        """
        Online: evaluate evidence coverage from real pipeline results.
        Offline (no pipeline_results): SKIP — synthetic benchmark products always have
        praise/complaints by construction, so an offline score measures benchmark-data
        completeness, not the production retrieval system (Gap #1). Excluded from the index.
        """
        pipeline_results: list[dict] = kwargs.get("pipeline_results", [])
        if pipeline_results:
            scores = [
                _eval_product_evidence(p)
                for run in pipeline_results
                for p in run.get("scored_products", [])
            ]
            avg = sum(scores) / max(len(scores), 1)
            threshold = PASS_THRESHOLDS[self.name]
            return MetricResult(
                name=self.name, score=round(avg, 1), passed=avg >= threshold,
                pass_threshold=threshold, details={"products_evaluated": len(scores)},
            )

        return MetricResult.skip(
            self.name, PASS_THRESHOLDS[self.name],
            "online-only: requires real pipeline output (pass pipeline_results)",
        )

    def _evaluate_offline_unused(self, scenarios: list[OfflineScenario], **kwargs) -> MetricResult:
        """Retained for reference — benchmark-data completeness check (not used in index)."""
        product_results = []

        seen = set()
        for s in scenarios:
            for product in s.products:
                if product.name in seen:
                    continue
                seen.add(product.name)

                praise_ok = len(product.praise) >= MIN_PRAISE_COUNT
                complaint_ok = len(product.complaints) >= MIN_COMPLAINT_COUNT
                mention_ok = product.mention_count >= MIN_MENTIONS
                signal_ok = product.signal_strength in ("strong", "moderate")

                sub_scores = {
                    "praise_coverage":   100.0 if praise_ok else 0.0,
                    "complaint_coverage": 100.0 if complaint_ok else 0.0,
                    "mention_volume":    min(product.mention_count / MIN_MENTIONS, 1.0) * 100,
                    "signal_strength":   100.0 if signal_ok else 50.0,
                }
                product_score = sum(sub_scores.values()) / len(sub_scores)

                issues = []
                if not praise_ok:
                    issues.append("no praise extracted")
                if not complaint_ok:
                    issues.append("no complaints extracted")
                if not mention_ok:
                    issues.append(f"only {product.mention_count} mentions (min {MIN_MENTIONS})")

                product_results.append({
                    "product": product.name,
                    "score": round(product_score, 1),
                    "passed": product_score >= 70.0,
                    "sub_scores": sub_scores,
                    "issues": issues,
                })

        if not product_results:
            score = 0.0
        else:
            score = sum(p["score"] for p in product_results) / len(product_results)

        threshold = PASS_THRESHOLDS[self.name]
        failures = [
            f"[{p['product']}] {i}" for p in product_results if p["issues"] for i in p["issues"]
        ]

        return MetricResult(
            name=self.name,
            score=round(score, 1),
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_products_evaluated": len(product_results),
                "products_passing": sum(1 for p in product_results if p["passed"]),
                "avg_mention_count": round(
                    sum(p["sub_scores"]["mention_volume"] for p in product_results) / max(len(product_results), 1), 1
                ),
                "products": product_results,
            },
            failures=failures[:20],
        )


class OnlineRetrievalQualityMetric(BaseMetric):
    """
    Online version: evaluates real pipeline results.
    Expects `pipeline_results` kwarg — list of scored_products dicts from the DB.
    """
    name = "retrieval_quality"
    phase = "Phase 6: Retrieval Quality (Online)"
    requires_pipeline = True

    def evaluate(self, scenarios: list, **kwargs) -> MetricResult:
        pipeline_results: list[dict] = kwargs.get("pipeline_results", [])
        threshold = PASS_THRESHOLDS[self.name]

        if not pipeline_results:
            return MetricResult(
                name=self.name, score=0.0, passed=False, pass_threshold=threshold,
                failures=["No pipeline results provided for online evaluation"],
            )

        product_scores = []
        for run in pipeline_results:
            for product in run.get("scored_products", []):
                score = _eval_product_evidence(product)
                product_scores.append(score)

        avg_score = sum(product_scores) / max(len(product_scores), 1)

        return MetricResult(
            name=self.name,
            score=round(avg_score, 1),
            passed=avg_score >= threshold,
            pass_threshold=threshold,
            details={"products_evaluated": len(product_scores)},
        )


def _eval_product_evidence(product: dict) -> float:
    """Score a single product's evidence coverage 0-100."""
    scores = []

    # Praise coverage
    praise = product.get("praise") or []
    scores.append(100.0 if len(praise) >= 1 else 0.0)

    # Complaint coverage
    complaints = product.get("complaints") or []
    scores.append(100.0 if len(complaints) >= 1 else 50.0)

    # Mention volume
    mentions = int(product.get("mention_count") or 0)
    scores.append(min(mentions / MIN_MENTIONS, 1.0) * 100)

    # Evidence quality in scores
    score_dicts = product.get("scores") or []
    default_count = sum(1 for s in score_dicts if "no direct data found" in s.get("evidence", ""))
    evidence_quality = max(0.0, 100.0 - (default_count / max(len(score_dicts), 1)) * 100)
    scores.append(evidence_quality)

    # Source diversity
    sources = product.get("sources") or []
    scores.append(min(len(sources) / 2, 1.0) * 100)

    return sum(scores) / len(scores)
