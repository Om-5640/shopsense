"""
Generic, data-driven benchmark pool loader.

Every benchmark category lives as a self-contained JSON file in evals/data/pools/.
This module reads ANY such file and converts it into the platform's dataclasses
(OfflineScenario, HumanJudgment) with ZERO hardcoded product, category, or criterion
names. Drop a new <category>.json into the pools directory and it is picked up
automatically — no code change required.

JSON pool schema (see evals/data/pools/_SCHEMA.md for the authoritative spec):

{
  "category":    "laptops",
  "description": "Laptop recommendation benchmarks",
  "criteria":    [ {"name": "performance", "label": "Processing Performance"}, ... ],
  "products":    [
    {
      "name": "BudgetBook L3",
      "scores": { "performance": 5, "battery_life": 7, ... },   // 0-10 per criterion
      "signal_strength": "moderate",                            // optional
      "mention_count": 28, "positive_mentions": 18, "negative_mentions": 10,  // optional
      "praise":     ["..."],                                    // optional
      "complaints": [ {"text": "...", "confidence": "high"} ]   // optional
    }, ...
  ],
  "scenarios": [
    {
      "id": "video_editor", "name": "Professional Video Editor",
      "tags": ["creative"],
      "weights": { "performance": 10, "display_quality": 9, ... },
      "expected_rank_1": "ProBook P8",
      "expected_rank_1_not": ["BudgetBook L3"],   // optional
      "expected_top_2": []                        // optional
    }, ...
  ],
  "human_judgments": [                            // optional
    {
      "id": "hj_video_editor", "name": "Expert — Video Editor",
      "query": "best laptop for video editing",
      "expert_rank_1": "ProBook P8", "expert_rank_2": "GameRig G7", "expert_rank_3": "UltraSlim U4",
      "expert_rationale": "...",
      "weights": { ... },
      "key_tradeoffs": ["..."]                    // optional
    }, ...
  ]
}

Referential integrity is enforced at load time: every product name referenced by a
scenario/judgment must exist, and every weight key must be a declared criterion. A
malformed pool raises PoolValidationError with a precise message instead of silently
producing wrong scores.
"""

from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache

from evals.benchmarks.base import (
    OfflineScenario, ProductProfile, RubricWeight, HumanJudgment,
)

# Pools live next to the eval data, discovered dynamically.
_POOLS_DIR = Path(__file__).resolve().parent.parent / "data" / "pools"

_VALID_SIGNAL = {"strong", "moderate", "weak", "high", "medium", "low"}


class PoolValidationError(ValueError):
    """Raised when a pool JSON file is structurally invalid or self-inconsistent."""


# ── Low-level builders ────────────────────────────────────────────────────────

def _build_product(raw: dict, criteria_names: set[str], pool_id: str) -> ProductProfile:
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise PoolValidationError(f"[{pool_id}] product missing a string 'name': {raw!r}")

    scores = raw.get("scores", {})
    if not isinstance(scores, dict) or not scores:
        raise PoolValidationError(f"[{pool_id}] product {name!r} has no 'scores' dict")

    unknown = set(scores) - criteria_names
    if unknown:
        raise PoolValidationError(
            f"[{pool_id}] product {name!r} scores unknown criteria {sorted(unknown)} "
            f"(declared criteria: {sorted(criteria_names)})"
        )

    # Clamp scores defensively to 0-10 so a typo can't skew the engine.
    clean_scores = {k: max(0.0, min(10.0, float(v))) for k, v in scores.items()}

    signal = str(raw.get("signal_strength", "moderate")).lower()
    if signal not in _VALID_SIGNAL:
        signal = "moderate"

    return ProductProfile(
        name=name,
        criterion_scores=clean_scores,
        signal_strength=signal,
        mention_count=int(raw.get("mention_count", 20)),
        positive_mentions=int(raw.get("positive_mentions", 14)),
        negative_mentions=int(raw.get("negative_mentions", 6)),
        praise=list(raw.get("praise", [])),
        complaints=list(raw.get("complaints", [])),
        evidence=dict(raw.get("evidence", {})),
    )


def _build_rubric(weights: dict, criteria: list[tuple[str, str]], pool_id: str,
                  ctx: str) -> list[RubricWeight]:
    """Build a full rubric: declared weights applied, all other criteria default to 0.0."""
    if not isinstance(weights, dict) or not weights:
        raise PoolValidationError(f"[{pool_id}] {ctx} has no 'weights' dict")

    name_to_label = dict(criteria)
    unknown = set(weights) - set(name_to_label)
    if unknown:
        raise PoolValidationError(
            f"[{pool_id}] {ctx} weights reference unknown criteria {sorted(unknown)}"
        )
    return [RubricWeight(name, label, float(weights.get(name, 0.0)))
            for name, label in criteria]


# ── Pool parsing ──────────────────────────────────────────────────────────────

def _parse_pool(path: Path) -> dict:
    """Parse a single pool JSON into {category, scenarios, human_judgments, products}."""
    pool_id = path.stem
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PoolValidationError(f"[{pool_id}] invalid JSON: {exc}") from exc

    criteria_raw = data.get("criteria")
    if not isinstance(criteria_raw, list) or not criteria_raw:
        raise PoolValidationError(f"[{pool_id}] missing non-empty 'criteria' list")

    criteria: list[tuple[str, str]] = []
    for c in criteria_raw:
        if not isinstance(c, dict) or "name" not in c:
            raise PoolValidationError(f"[{pool_id}] malformed criterion entry: {c!r}")
        criteria.append((c["name"], c.get("label", c["name"])))
    criteria_names = {n for n, _ in criteria}

    # Products
    products_raw = data.get("products")
    if not isinstance(products_raw, list) or len(products_raw) < 2:
        raise PoolValidationError(f"[{pool_id}] needs at least 2 products")
    products = [_build_product(p, criteria_names, pool_id) for p in products_raw]
    product_names = {p.name for p in products}

    category = data.get("category", pool_id)

    # Scenarios
    scenarios: list[OfflineScenario] = []
    for s in data.get("scenarios", []):
        sid = s.get("id", "?")
        ctx = f"scenario {sid!r}"
        rank1 = s.get("expected_rank_1")
        if rank1 not in product_names:
            raise PoolValidationError(
                f"[{pool_id}] {ctx} expected_rank_1={rank1!r} is not a known product"
            )
        for ref_key in ("expected_rank_1_not", "expected_top_2"):
            for nm in s.get(ref_key, []):
                if nm not in product_names:
                    raise PoolValidationError(
                        f"[{pool_id}] {ctx} {ref_key} references unknown product {nm!r}"
                    )
        rubric = _build_rubric(s.get("weights", {}), criteria, pool_id, ctx)
        scenarios.append(OfflineScenario(
            id=f"{pool_id}_{sid}",
            name=s.get("name", sid),
            description=s.get("description", s.get("name", sid)),
            tags=list(s.get("tags", [])) + [category],
            products=products,
            rubric_weights=rubric,
            expected_rank_1=rank1,
            expected_rank_1_not=list(s.get("expected_rank_1_not", [])),
            expected_top_2=list(s.get("expected_top_2", [])),
            constraint_hard=list(s.get("constraint_hard", [])),
            constraint_budget=s.get("constraint_budget"),
            intent=dict(s.get("intent", {})),
            phase=f"Phase 2 — {category}",
        ))

    # Human judgments
    judgments: list[HumanJudgment] = []
    for h in data.get("human_judgments", []):
        hid = h.get("id", "?")
        ctx = f"human_judgment {hid!r}"
        for rk in ("expert_rank_1", "expert_rank_2", "expert_rank_3"):
            nm = h.get(rk)
            if nm not in product_names:
                raise PoolValidationError(
                    f"[{pool_id}] {ctx} {rk}={nm!r} is not a known product"
                )
        rubric = _build_rubric(h.get("weights", {}), criteria, pool_id, ctx)
        judgments.append(HumanJudgment(
            id=f"{pool_id}_{hid}",
            name=h.get("name", hid),
            query=h.get("query", ""),
            expert_rank_1=h["expert_rank_1"],
            expert_rank_2=h["expert_rank_2"],
            expert_rank_3=h["expert_rank_3"],
            expert_rationale=h.get("expert_rationale", ""),
            products=products,
            rubric_weights=rubric,
            key_tradeoffs=list(h.get("key_tradeoffs", [])),
        ))

    return {
        "category": category,
        "products": products,
        "scenarios": scenarios,
        "human_judgments": judgments,
    }


# ── Public API ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_all_pools() -> tuple[dict, ...]:
    """
    Discover and parse every <category>.json in evals/data/pools/.
    Files whose names start with '_' (e.g. _SCHEMA) are ignored.
    Cached for the process lifetime. Returns a tuple of parsed-pool dicts.
    """
    if not _POOLS_DIR.exists():
        return ()
    pools = []
    for path in sorted(_POOLS_DIR.glob("*.json")):
        if path.stem.startswith("_"):
            continue
        pools.append(_parse_pool(path))
    return tuple(pools)


def pool_scenarios() -> list[OfflineScenario]:
    """All offline scenarios across every JSON pool."""
    out: list[OfflineScenario] = []
    for pool in load_all_pools():
        out.extend(pool["scenarios"])
    return out


def pool_human_judgments() -> list[HumanJudgment]:
    """All human judgments across every JSON pool."""
    out: list[HumanJudgment] = []
    for pool in load_all_pools():
        out.extend(pool["human_judgments"])
    return out


def pool_categories() -> list[str]:
    """Names of all discovered categories."""
    return [pool["category"] for pool in load_all_pools()]
