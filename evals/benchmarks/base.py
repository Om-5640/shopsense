"""
Core dataclasses for the ShopSense evaluation platform.

All benchmark scenarios are expressed through these types.
Offline scenarios require no LLM calls — the scoring math is pure Python.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CriterionDef:
    name: str   # snake_case
    label: str  # Human-readable


@dataclass
class RubricWeight:
    criterion: str
    label: str
    weight: float  # 0-10


@dataclass
class ProductProfile:
    name: str
    criterion_scores: dict[str, float]   # criterion_name -> 0-10
    signal_strength: str = "moderate"
    mention_count: int = 20
    positive_mentions: int = 14
    negative_mentions: int = 6
    praise: list[str] = field(default_factory=list)
    complaints: list[dict] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)


@dataclass
class OfflineScenario:
    id: str
    name: str
    description: str
    tags: list[str]

    products: list[ProductProfile]
    rubric_weights: list[RubricWeight]

    expected_rank_1: str
    expected_rank_1_not: list[str] = field(default_factory=list)
    expected_top_2: list[str] = field(default_factory=list)
    constraint_hard: list[str] = field(default_factory=list)
    constraint_budget: Optional[str] = None
    intent: dict = field(default_factory=dict)
    phase: str = "Phase 2"


@dataclass
class SemanticCluster:
    id: str
    name: str
    description: str
    variants: list[str]              # Semantically equivalent query strings
    expected_top_products: list[str] # Must appear in top-3 for every variant
    rubric_weights: list[RubricWeight]
    products: list[ProductProfile]


@dataclass
class CounterfactualPair:
    id: str
    name: str
    description: str
    changed_criterion: str
    base_rubric: list[RubricWeight]
    modified_rubric: list[RubricWeight]
    products: list[ProductProfile]
    base_winner: str
    modified_winner: str
    must_differ: bool = True


@dataclass
class PersonaRubric:
    persona_id: str
    persona_name: str
    rubric_weights: list[RubricWeight]
    expected_rank_1: str


@dataclass
class PersonalizationTest:
    id: str
    name: str
    description: str
    query: str
    personas: list[PersonaRubric]
    products: list[ProductProfile]
    min_rank_1_diversity: int = 2   # Distinct rank-1 winners across personas


@dataclass
class AdversarialScenario:
    id: str
    name: str
    description: str
    attack_type: str
    injected_content: str
    safe_rubric: list[RubricWeight]
    safe_products: list[ProductProfile]
    attack_target: str
    expected_safe_winner: str


@dataclass
class HumanJudgment:
    id: str
    name: str
    query: str
    expert_rank_1: str
    expert_rank_2: str
    expert_rank_3: str
    expert_rationale: str
    products: list[ProductProfile]
    rubric_weights: list[RubricWeight]
    key_tradeoffs: list[str] = field(default_factory=list)
