"""
Benchmark aggregation.

The earbuds suite (users.py / human_judgments.py) is the original hand-written pool.
Additional categories live as JSON files in evals/data/pools/ and are discovered
automatically by pool_loader — no code change needed to add a category.

all_scenarios() and all_human_judgments() return the UNION of the earbuds suite and
every JSON pool, so all downstream metrics (recommendation, ranking, personalization,
human-alignment) evaluate across every category at once.
"""

from .users import all_scenarios as _earbuds_scenarios, scenarios_by_tag
from .semantic_clusters import all_clusters
from .counterfactuals import all_counterfactuals
from .personalization import all_personalization_tests
from .adversarial import all_adversarial
from .human_judgments import all_human_judgments as _earbuds_human_judgments
from .pool_loader import pool_scenarios, pool_human_judgments, pool_categories


def all_scenarios():
    """Every offline scenario: earbuds suite + all JSON category pools."""
    return _earbuds_scenarios() + pool_scenarios()


def all_human_judgments():
    """Every expert judgment: earbuds suite + all JSON category pools."""
    return _earbuds_human_judgments() + pool_human_judgments()


def all_categories():
    """Discovered category names (earbuds is implicit; JSON pools are explicit)."""
    return ["earbuds"] + pool_categories()


__all__ = [
    "all_scenarios",
    "scenarios_by_tag",
    "all_clusters",
    "all_counterfactuals",
    "all_personalization_tests",
    "all_adversarial",
    "all_human_judgments",
    "all_categories",
]
