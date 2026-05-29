"""
Base class and result types for all metrics.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class MetricResult:
    name: str
    score: float           # 0-100
    passed: bool
    pass_threshold: float
    details: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        if self.score >= 90: return "A"
        if self.score >= 80: return "B"
        if self.score >= 70: return "C"
        if self.score >= 60: return "D"
        return "F"


@dataclass
class ScenarioResult:
    scenario_id: str
    scenario_name: str
    tags: list[str]
    passed: bool
    score: float
    failures: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


class BaseMetric(ABC):
    name: str = "base_metric"
    phase: str = "Phase 0"
    requires_pipeline: bool = False  # True = online only

    @abstractmethod
    def evaluate(self, scenarios: list, **kwargs) -> MetricResult:
        ...
