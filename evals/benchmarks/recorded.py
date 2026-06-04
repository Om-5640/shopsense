"""
Recorded real-pipeline fixtures.

These are captured outputs from real pipeline runs (real Reddit threads → real LLM
analysis → real scored products). They are committed so CI can measure the quality of
*actual model output* — extraction, evidence grounding, retrieval coverage — deterministically
and for free, without burning API rate limits on every build.

Two consumers:
  - load_recorded_pipeline_results() feeds `retrieval_quality` and `explanation_integrity`
    so those online-only metrics produce REAL scores in CI instead of skipping.
  - tests/evals/test_recorded_pipeline.py asserts extraction recall + grounding thresholds.

Capture a fresh fixture after a real run with:  python -m evals.online.record
"""

from __future__ import annotations

import json
from pathlib import Path

_RECORDED_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "recorded"


def _load_files() -> list[dict]:
    if not _RECORDED_DIR.exists():
        return []
    out = []
    for path in sorted(_RECORDED_DIR.glob("*.json")):
        if path.stem.startswith("_"):
            continue
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def load_recorded_pipeline_results() -> list[dict]:
    """
    Return a list of {scored_products: [...]} dicts in the shape the online metrics expect.
    Empty list when no fixtures exist (metrics then fall back to skipping).
    """
    return [
        {"scored_products": f.get("scored_products", [])}
        for f in _load_files()
        if f.get("scored_products")
    ]


def load_recorded_fixtures() -> list[dict]:
    """Return the full recorded fixtures (incl. _meta with expected_products and source_excerpt)."""
    return _load_files()


def has_recorded_fixtures() -> bool:
    return bool(_load_files())
