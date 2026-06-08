"""
Stage Fault Injection Benchmark.

Injects four known pipeline corruptions into every benchmark scenario and
verifies that each corruption produces a measurable rank change in the final
ranked output.  If a corruption does NOT move rank, the pipeline has a blind
spot in that stage.

Four fault types:
  RETRIEVAL_MISS         — simulate 0 Reddit threads retrieved for target product:
                           all criterion_scores → 1.0, mention_count → 0
  MENTION_COUNT_HALVING  — simulate 50 % thread loss with reduced evidence quality:
                           mention_count halved, all criterion_scores reduced by 3.5
  EVIDENCE_HALLUCINATION — simulate LLM inflating a weak product's scores:
                           all criterion_scores → 9.0
  SCORE_DRIFT            — simulate systematic +3.5 bias on the rank-2 product:
                           all criterion_scores + 3.5 (cap 10.0)

Fault magnitudes are sized so that on any realistic product dataset the
corruption moves the target across at least one rank boundary.  Structurally
impossible scenarios (fewer than 2 products) are silently skipped.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum

from evals.benchmarks.base import ProductProfile, RubricWeight
from evals.engine import build_scored_products, rank_of


# ── Fault taxonomy ────────────────────────────────────────────────────────────

class FaultType(str, Enum):
    RETRIEVAL_MISS = "retrieval_miss"
    MENTION_COUNT_HALVING = "mention_count_halving"
    EVIDENCE_HALLUCINATION = "evidence_hallucination"
    SCORE_DRIFT = "score_drift"


# ── Scenario dataclass ────────────────────────────────────────────────────────

@dataclass
class FaultScenario:
    id: str
    name: str
    fault_type: FaultType
    products: list[ProductProfile]
    rubric: list[RubricWeight]
    target_product: str    # product being corrupted
    detection: str         # "rank_drops" | "rank_rises"
    description: str = ""
    source_fixture: str = ""


# ── Core fault injection ──────────────────────────────────────────────────────

def inject_fault(
    scenario: FaultScenario,
) -> tuple[list[ProductProfile], list[ProductProfile]]:
    """
    Returns (baseline_products, corrupted_products) — deepcopy-isolated.
    Baseline is untouched; corrupted has the target product's data modified
    according to the scenario's fault_type.
    """
    baseline = copy.deepcopy(scenario.products)
    corrupted = copy.deepcopy(scenario.products)

    idx = next(
        (i for i, p in enumerate(corrupted) if p.name == scenario.target_product),
        None,
    )
    if idx is None:
        return baseline, corrupted  # target not found — no-op

    target = corrupted[idx]
    ft = scenario.fault_type

    if ft == FaultType.RETRIEVAL_MISS:
        # Pipeline found 0 threads: default-low confidence on every criterion
        target.criterion_scores = {k: 1.0 for k in target.criterion_scores}
        target.mention_count = 0
        target.positive_mentions = 0
        target.negative_mentions = 0

    elif ft == FaultType.MENTION_COUNT_HALVING:
        # 50 % of threads not scraped: fewer samples → lower evidence quality
        target.mention_count = max(0, target.mention_count // 2)
        target.positive_mentions = max(0, target.positive_mentions // 2)
        target.negative_mentions = max(0, target.negative_mentions // 2)
        target.criterion_scores = {
            k: max(0.0, v - 3.5) for k, v in target.criterion_scores.items()
        }

    elif ft == FaultType.EVIDENCE_HALLUCINATION:
        # LLM invented high-quality evidence for a weak product
        target.criterion_scores = {k: 9.0 for k in target.criterion_scores}
        target.positive_mentions = 50

    elif ft == FaultType.SCORE_DRIFT:
        # Systematic generous-scoring bias on the rank-2 product
        target.criterion_scores = {
            k: min(10.0, v + 3.5) for k, v in target.criterion_scores.items()
        }

    return baseline, corrupted


# ── Detection logic ───────────────────────────────────────────────────────────

def is_detected(
    scenario: FaultScenario,
    baseline_ranked: list[dict],
    corrupted_ranked: list[dict],
) -> tuple[bool, str]:
    """
    Returns (detected, explanation).
    detected=True means the fault produced a measurable rank change.
    """
    baseline_rank = rank_of(baseline_ranked, scenario.target_product)
    corrupted_rank = rank_of(corrupted_ranked, scenario.target_product)

    if scenario.detection == "rank_drops":
        detected = corrupted_rank > baseline_rank
    elif scenario.detection == "rank_rises":
        detected = corrupted_rank < baseline_rank
    else:
        return False, f"unknown detection mode: {scenario.detection!r}"

    explanation = (
        f"{scenario.target_product}: rank {baseline_rank}→{corrupted_rank} "
        f"({'DETECTED' if detected else 'NO CHANGE — blind spot'})"
    )
    return detected, explanation


# ── Scenario builders ─────────────────────────────────────────────────────────

def _build_scenarios_for_source(
    products: list[ProductProfile],
    rubric: list[RubricWeight],
    source_id: str,
) -> list[FaultScenario]:
    """
    Generate the four canonical fault scenarios for a product set.
    Returns an empty list if fewer than 2 products (structurally impossible).
    """
    if len(products) < 2:
        return []

    baseline = build_scored_products(products, rubric)
    rank1_name = baseline[0]["name"]
    last_name = baseline[-1]["name"]
    rank2_name = baseline[1]["name"]  # safe: len >= 2

    return [
        FaultScenario(
            id=f"{source_id}_retrieval_miss",
            name=f"{source_id} — Retrieval Miss",
            fault_type=FaultType.RETRIEVAL_MISS,
            products=products,
            rubric=rubric,
            target_product=rank1_name,
            detection="rank_drops",
            description=(
                f"Set all criterion_scores of '{rank1_name}' to 1.0 and "
                "mention_count to 0 — simulates 0 Reddit threads retrieved"
            ),
            source_fixture=source_id,
        ),
        FaultScenario(
            id=f"{source_id}_mention_halving",
            name=f"{source_id} — Mention Count Halving",
            fault_type=FaultType.MENTION_COUNT_HALVING,
            products=products,
            rubric=rubric,
            target_product=rank1_name,
            detection="rank_drops",
            description=(
                f"Halve mention counts and reduce all criterion_scores of "
                f"'{rank1_name}' by 3.5 — simulates 50 % thread loss"
            ),
            source_fixture=source_id,
        ),
        FaultScenario(
            id=f"{source_id}_evidence_hallucination",
            name=f"{source_id} — Evidence Hallucination",
            fault_type=FaultType.EVIDENCE_HALLUCINATION,
            products=products,
            rubric=rubric,
            target_product=last_name,
            detection="rank_rises",
            description=(
                f"Set all criterion_scores of '{last_name}' to 9.0 — "
                "simulates LLM hallucinating positive evidence for a weak product"
            ),
            source_fixture=source_id,
        ),
        FaultScenario(
            id=f"{source_id}_score_drift",
            name=f"{source_id} — Score Drift",
            fault_type=FaultType.SCORE_DRIFT,
            products=products,
            rubric=rubric,
            target_product=rank2_name,
            detection="rank_rises",
            description=(
                f"Boost all criterion_scores of '{rank2_name}' by +3.5 — "
                "simulates systematic generous-scoring bias on rank-2"
            ),
            source_fixture=source_id,
        ),
    ]


# ── Public generators ─────────────────────────────────────────────────────────

def generate_fault_scenarios_from_pools() -> list[FaultScenario]:
    """
    Generate 4 fault scenarios per pool-based offline scenario
    (earbuds suite + all JSON category pools).
    """
    from evals.benchmarks import all_scenarios
    out: list[FaultScenario] = []
    for scene in all_scenarios():
        out.extend(
            _build_scenarios_for_source(
                products=scene.products,
                rubric=scene.rubric_weights,
                source_id=scene.id,
            )
        )
    return out


def generate_fault_scenarios_from_recorded() -> list[FaultScenario]:
    """
    Generate 4 fault scenarios per recorded real-pipeline fixture.
    Uses equal-weight rubric across all criteria found in the fixture.
    """
    from evals.benchmarks.recorded import load_recorded_fixtures
    out: list[FaultScenario] = []
    for fixture in load_recorded_fixtures():
        products = _products_from_recorded(fixture)
        if len(products) < 2:
            continue
        rubric = _equal_weight_rubric(products)
        meta = fixture.get("_meta", {})
        query = str(meta.get("query", "fixture"))[:40].replace(" ", "_")
        source_id = f"recorded_{query}"
        out.extend(_build_scenarios_for_source(products, rubric, source_id))
    return out


def all_fault_scenarios() -> list[FaultScenario]:
    """All fault scenarios: pool-based + recorded fixtures."""
    return (
        generate_fault_scenarios_from_pools()
        + generate_fault_scenarios_from_recorded()
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _products_from_recorded(fixture: dict) -> list[ProductProfile]:
    """Convert recorded fixture scored_products to ProductProfile objects."""
    out: list[ProductProfile] = []
    for sp in fixture.get("scored_products", []):
        criterion_scores = {
            s["criterion"]: float(s.get("score", 5.0))
            for s in sp.get("scores", [])
            if "criterion" in s
        }
        if not criterion_scores:
            continue
        out.append(ProductProfile(
            name=sp["name"],
            criterion_scores=criterion_scores,
            signal_strength=str(sp.get("signal_strength", "moderate")),
            mention_count=int(sp.get("mention_count", 20)),
            positive_mentions=int(sp.get("positive_mentions", 14)),
            negative_mentions=int(sp.get("negative_mentions", 6)),
            praise=list(sp.get("praise", [])),
            complaints=list(sp.get("complaints", [])),
        ))
    return out


def _equal_weight_rubric(products: list[ProductProfile]) -> list[RubricWeight]:
    """Build an equal-weight (5.0 each) rubric from all criteria across products."""
    seen: dict[str, bool] = {}
    for p in products:
        for crit in p.criterion_scores:
            seen[crit] = True
    return [RubricWeight(criterion=c, label=c, weight=5.0) for c in seen]
