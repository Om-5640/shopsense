"""
Fix 19: Ranking Stability Metric.

Measures whether the scoring engine produces consistent rankings when rubric
weights are perturbed by ±10% Gaussian noise.

Algorithm:
  1. For each StabilityScenario, build the base ranking using engine.build_scored_products()
  2. Apply N_PERTURBATIONS random weight perturbations (Gaussian noise, σ = 10% of weight,
     clipped so no weight goes negative, then re-normalised to keep the same total)
  3. Re-rank with engine.rerank_with_rubric() for each perturbed rubric
  4. Compute Spearman ρ between the base ranking and each perturbed ranking
  5. Report mean ρ as the stability score for this scenario

Per-scenario score = mean Spearman ρ × 100
Overall metric score = mean of per-scenario scores.

All arithmetic is deterministic pure-Python — zero LLM calls.
Random seed is fixed per scenario id so CI runs are reproducible.
"""

from __future__ import annotations
import hashlib
import random

from evals.benchmarks.ranking_stability import StabilityScenario
from evals.benchmarks.base import RubricWeight
from evals.engine import build_scored_products, rerank_with_rubric, rank_names
from evals.metrics.base import BaseMetric, MetricResult
from evals.config import PASS_THRESHOLDS

N_PERTURBATIONS = 5
NOISE_SIGMA_FRACTION = 0.10  # σ = 10% of each weight


def _stable_seed(scenario_id: str) -> int:
    """Derive a deterministic integer seed from the scenario id."""
    return int(hashlib.md5(scenario_id.encode()).hexdigest()[:8], 16)


def _perturb_rubric(
    rubric: list[RubricWeight],
    rng: random.Random,
) -> list[RubricWeight]:
    """
    Apply independent Gaussian noise to each weight.
    Noise σ = NOISE_SIGMA_FRACTION × weight_value.
    Clip to minimum 1e-6 so no criterion disappears entirely.
    The total sum of weights is preserved (re-normalised to original sum).
    """
    original_total = sum(r.weight for r in rubric)
    noisy: list[float] = []
    for r in rubric:
        sigma = NOISE_SIGMA_FRACTION * r.weight
        new_w = r.weight + rng.gauss(0.0, sigma)
        noisy.append(max(1e-6, new_w))

    # Re-normalise to keep total weight unchanged
    noisy_total = sum(noisy)
    if noisy_total > 0:
        scale = original_total / noisy_total
        noisy = [w * scale for w in noisy]

    return [
        RubricWeight(criterion=r.criterion, label=r.label, weight=round(noisy[i], 6))
        for i, r in enumerate(rubric)
    ]


def _spearman(r1: list[str], r2: list[str]) -> float:
    """
    Pure-Python Spearman rank correlation.
    Uses only products present in both rankings (handles set differences gracefully).
    Returns 1.0 when fewer than 2 common products exist.
    """
    rank1 = {name: i for i, name in enumerate(r1)}
    rank2 = {name: i for i, name in enumerate(r2)}
    common = [name for name in r1 if name in rank2]
    n = len(common)
    if n <= 1:
        return 1.0
    d_sq = sum((rank1[name] - rank2[name]) ** 2 for name in common)
    denom = n * (n ** 2 - 1)
    if denom == 0:
        return 1.0
    return 1.0 - 6.0 * d_sq / denom


class RankingStabilityMetric(BaseMetric):
    name = "ranking_stability"
    phase = "Fix 19: Ranking Stability"

    def evaluate(
        self,
        scenarios: list[StabilityScenario],
        **kwargs,
    ) -> MetricResult:
        threshold = PASS_THRESHOLDS.get(self.name, 70.0)

        if not scenarios:
            return MetricResult.skip(
                name=self.name,
                threshold=threshold,
                reason="no stability scenarios provided",
            )

        failures: list[str] = []
        scenario_details: list[dict] = []
        per_scores: list[float] = []

        for sc in scenarios:
            rng = random.Random(_stable_seed(sc.id))

            # Base ranking
            base_scored = build_scored_products(sc.products, sc.base_rubric)
            base_names = rank_names(base_scored)

            spearman_values: list[float] = []
            perturbation_details: list[dict] = []

            for i in range(N_PERTURBATIONS):
                perturbed_rubric = _perturb_rubric(sc.base_rubric, rng)
                perturbed_scored = rerank_with_rubric(base_scored, perturbed_rubric)
                perturbed_names = rank_names(perturbed_scored)
                rho = _spearman(base_names, perturbed_names)
                spearman_values.append(rho)
                perturbation_details.append({
                    "perturbation": i + 1,
                    "spearman_rho": round(rho, 4),
                    "base_rank_1": base_names[0] if base_names else "",
                    "perturbed_rank_1": perturbed_names[0] if perturbed_names else "",
                    "rank_1_stable": (
                        (base_names[:1] == perturbed_names[:1])
                        if base_names and perturbed_names
                        else True
                    ),
                })

            mean_rho = sum(spearman_values) / len(spearman_values) if spearman_values else 0.0
            scenario_score = round(mean_rho * 100.0, 1)
            per_scores.append(scenario_score)

            if mean_rho < sc.min_spearman - 1e-6:
                failures.append(
                    f"[{sc.id}] mean_spearman={mean_rho:.3f} < min={sc.min_spearman:.2f}"
                    f" — {sc.description}"
                )

            scenario_details.append({
                "id": sc.id,
                "description": sc.description,
                "category": sc.category,
                "n_products": len(sc.products),
                "n_criteria": len(sc.base_rubric),
                "mean_spearman": round(mean_rho, 4),
                "min_spearman": sc.min_spearman,
                "scenario_score": scenario_score,
                "rank_1_stable_count": sum(
                    1 for p in perturbation_details if p["rank_1_stable"]
                ),
                "perturbations": perturbation_details,
            })

        score = round(sum(per_scores) / len(per_scores), 1) if per_scores else 0.0

        return MetricResult(
            name=self.name,
            score=score,
            passed=score >= threshold,
            pass_threshold=threshold,
            details={
                "total_scenarios": len(scenarios),
                "n_perturbations": N_PERTURBATIONS,
                "noise_sigma_fraction": NOISE_SIGMA_FRACTION,
                "scenarios_above_threshold": sum(
                    1 for d in scenario_details
                    if d["mean_spearman"] >= d["min_spearman"] - 1e-6
                ),
                "scenario_details": scenario_details,
            },
            failures=failures,
        )
