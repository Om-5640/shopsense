"""
Phase 8: Explanation Integrity

Detects:
  - Default/fallback evidence ("no direct data found") — indicates missing retrieval
  - Score/evidence inconsistency (high score with negative evidence text)
  - Post-hoc justification signals (evidence doesn't support score)
  - Missing evidence (empty string evidence)

In offline mode: checks synthetic benchmark products for evidence quality signals.
In online mode: evaluates real LLM-generated evidence from pipeline output.
"""

from __future__ import annotations
import re
from evals.benchmarks.base import OfflineScenario
from evals.engine import build_scored_products
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS

# Evidence that indicates the LLM didn't find real data
DEFAULT_EVIDENCE_PATTERNS = [
    "no direct data found",
    "no evidence",
    "insufficient data",
    "not mentioned",
    "unclear from research",
    "benchmark synthetic data",  # our own offline placeholder
]

# Negative sentiment words that signal a contradiction with high scores
NEGATIVE_KEYWORDS = [
    "poor", "bad", "terrible", "disappointing", "worst", "fails", "broken",
    "recall", "defective", "dangerous", "avoid", "complaint", "problem",
]


class ExplanationIntegrityMetric(BaseMetric):
    name = "explanation_integrity"
    phase = "Phase 8: Explanation Integrity"

    def evaluate(self, scenarios: list[OfflineScenario], **kwargs) -> MetricResult:
        """
        Offline mode: uses synthetic evidence fields.
        Online mode: pass pipeline_results kwarg.
        """
        pipeline_results: list[dict] = kwargs.get("pipeline_results", [])

        if pipeline_results:
            return self._evaluate_online(pipeline_results)
        return self._evaluate_offline(scenarios)

    def _evaluate_offline(self, scenarios: list[OfflineScenario]) -> MetricResult:
        """
        Explanation integrity is meaningless on synthetic offline data — the evidence
        strings are placeholders, not real LLM output. Rather than fake a score that
        masquerades as LLM-quality measurement (Gap #1), we SKIP it offline. It is
        excluded from the Intelligence Index. Pass pipeline_results to measure it for real.
        """
        return MetricResult.skip(
            self.name, PASS_THRESHOLDS[self.name],
            "online-only: requires real pipeline output (pass pipeline_results)",
        )

    def _evaluate_online(self, pipeline_results: list[dict]) -> MetricResult:
        all_product_scores = []
        issues = []

        for run in pipeline_results:
            for product in run.get("scored_products", []):
                integrity = _score_product_integrity(product)
                all_product_scores.append(integrity)

                product_issues = _find_integrity_issues(product)
                for issue in product_issues:
                    issues.append(f"[{product.get('name', '?')}] {issue}")

        avg = sum(all_product_scores) / max(len(all_product_scores), 1)
        threshold = PASS_THRESHOLDS[self.name]

        return MetricResult(
            name=self.name,
            score=round(avg, 1),
            passed=avg >= threshold,
            pass_threshold=threshold,
            details={
                "products_evaluated": len(all_product_scores),
                "issues_found": len(issues),
            },
            failures=issues[:20],
        )


def _score_product_integrity(product: dict) -> float:
    """Score a product's explanation integrity 0-100."""
    score_list = product.get("scores") or []
    if not score_list:
        return 50.0

    sub_scores = []

    for s in score_list:
        evidence = (s.get("evidence") or "").lower().strip()
        score_val = float(s.get("score") or 5.0)

        # Penalise default/no-data evidence
        is_default = any(pat in evidence for pat in DEFAULT_EVIDENCE_PATTERNS)
        sub_scores.append(0.5 if is_default else 1.0)

        # Penalise empty evidence
        if not evidence:
            sub_scores.append(0.3)
            continue

        # Penalise score/evidence contradictions
        has_negative = any(kw in evidence for kw in NEGATIVE_KEYWORDS)
        if score_val >= 8.0 and has_negative:
            sub_scores.append(0.2)

    avg = sum(sub_scores) / max(len(sub_scores), 1)
    return round(avg * 100, 1)


def _find_integrity_issues(product: dict) -> list[str]:
    """Return list of integrity issue strings for a single product."""
    issues = []
    score_list = product.get("scores") or []
    default_count = 0
    empty_count = 0
    contradiction_count = 0

    for s in score_list:
        evidence = (s.get("evidence") or "").lower().strip()
        score_val = float(s.get("score") or 5.0)

        if any(pat in evidence for pat in DEFAULT_EVIDENCE_PATTERNS):
            default_count += 1
        if not evidence:
            empty_count += 1
        if score_val >= 8.0 and any(kw in evidence for kw in NEGATIVE_KEYWORDS):
            contradiction_count += 1

    n = max(len(score_list), 1)
    if default_count / n > 0.5:
        issues.append(f"{default_count}/{len(score_list)} criteria have default evidence")
    if empty_count > 0:
        issues.append(f"{empty_count} criteria have empty evidence")
    if contradiction_count > 0:
        issues.append(f"{contradiction_count} criteria have score/evidence contradictions")

    return issues
