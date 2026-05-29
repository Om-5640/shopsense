"""
Pure-Python scoring engine for offline evals.

Mirrors scorer.py's _build_scored_dict math exactly, but has zero
production imports — keeping the eval platform self-contained.
"""

from __future__ import annotations
from evals.benchmarks.base import ProductProfile, RubricWeight


def build_scored_products(
    products: list[ProductProfile],
    rubric: list[RubricWeight],
) -> list[dict]:
    """
    Score products against rubric weights. Pure math — no LLM calls.
    Returns list sorted by weighted_total descending (same as production scorer).
    """
    results = []
    for p in products:
        scores = []
        weighted_total = 0.0
        max_possible = 0.0

        for r in rubric:
            raw = p.criterion_scores.get(r.criterion, 5.0)
            score = max(0.0, min(10.0, float(raw)))
            weight = float(r.weight)
            weighted_total += score * weight
            max_possible += 10.0 * weight

            scores.append({
                "criterion": r.criterion,
                "label": r.label,
                "weight": weight,
                "score": score,
                "evidence": p.evidence.get(r.criterion, "benchmark synthetic data"),
                "weighted_contribution": round(score * weight, 1),
            })

        pct = (weighted_total / max_possible * 100) if max_possible > 0 else 0.0

        results.append({
            "name": p.name,
            "signal_strength": p.signal_strength,
            "scores": scores,
            "weighted_total": round(weighted_total, 1),
            "max_possible": round(max_possible, 1),
            "percentage": round(pct, 1),
            "mention_count": p.mention_count,
            "positive_mentions": p.positive_mentions,
            "negative_mentions": p.negative_mentions,
            "praise": p.praise,
            "complaints": p.complaints,
        })

    return sorted(results, key=lambda x: x["weighted_total"], reverse=True)


def rerank_with_rubric(
    scored: list[dict],
    new_rubric: list[RubricWeight],
) -> list[dict]:
    """Re-rank already-scored products using new rubric weights. No LLM."""
    new_weights = {r.criterion: r.weight for r in new_rubric}
    rescored = []
    for p in scored:
        weighted_total = 0.0
        max_possible = 0.0
        new_scores = []
        for s in p["scores"]:
            w = float(new_weights.get(s["criterion"], s["weight"]))
            weighted_total += s["score"] * w
            max_possible += 10.0 * w
            new_scores.append({**s, "weight": w, "weighted_contribution": round(s["score"] * w, 1)})
        pct = (weighted_total / max_possible * 100) if max_possible > 0 else 0.0
        rescored.append({
            **p,
            "scores": new_scores,
            "weighted_total": round(weighted_total, 1),
            "max_possible": round(max_possible, 1),
            "percentage": round(pct, 1),
        })
    return sorted(rescored, key=lambda x: x["weighted_total"], reverse=True)


def rank_names(scored: list[dict]) -> list[str]:
    """Return product names in rank order."""
    return [p["name"] for p in scored]


def score_for(scored: list[dict], name: str) -> float:
    """Return percentage score for a named product, or 0 if not found."""
    for p in scored:
        if p["name"] == name:
            return p["percentage"]
    return 0.0


def rank_of(scored: list[dict], name: str) -> int:
    """Return 1-based rank of a named product, or len+1 if not found."""
    for i, p in enumerate(scored, 1):
        if p["name"] == name:
            return i
    return len(scored) + 1
