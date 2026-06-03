"""
Shared fixtures and helpers for golden-file eval tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))

import os
os.environ.setdefault("GEMINI_API_KEY",    "dummy")
os.environ.setdefault("GROQ_API_KEY",      "dummy")
os.environ.setdefault("SERPER_API_KEY",    "dummy")
os.environ.setdefault("OPENROUTER_API_KEY","dummy")

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Required keys every normalized product must have
REQUIRED_PRODUCT_KEYS = {
    "name", "mention_count", "distinct_recommenders",
    "positive_mentions", "negative_mentions",
    "praise", "complaints", "sources",
    "signal_strength", "representative_quote", "cross_subreddit_signal",
}


def load_fixture(fixture_id: str) -> dict:
    path = FIXTURES_DIR / f"{fixture_id}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def all_normalizer_fixtures() -> list[str]:
    """Return IDs of all non-scorer fixtures."""
    return [
        p.stem for p in sorted(FIXTURES_DIR.glob("*.json"))
        if not p.stem.startswith("scorer_")
    ]


def all_scorer_fixtures() -> list[str]:
    return [p.stem for p in sorted(FIXTURES_DIR.glob("scorer_*.json"))]


def assert_product_schema(product: dict) -> None:
    missing = REQUIRED_PRODUCT_KEYS - set(product.keys())
    assert not missing, f"Product '{product.get('name')}' missing keys: {missing}"
    assert isinstance(product["praise"], list)
    assert isinstance(product["complaints"], list)
    assert isinstance(product["sources"], list)
    for c in product["complaints"]:
        assert isinstance(c, dict), f"Complaint must be dict, got {type(c)}"
        assert "text" in c and "confidence" in c
        assert c["confidence"] in ("confirmed", "reported", "single")
    assert product["signal_strength"] in ("high", "medium", "low")
    assert product["mention_count"] >= 0
    assert product["positive_mentions"] >= 0
    assert product["negative_mentions"] >= 0
