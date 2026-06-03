"""
Golden-file tests for scorer._build_scored_dict() — pure math, zero LLM calls.

These tests assert that given known LLM scores and a known rubric, the
weighted percentage matches the expected value within ±0.5 percentage points.

If this test fails, it means either:
  - The scoring math changed (intentional → update fixture)
  - A provider returned different scores for the same product (regression)
  - _compute_percentage has a precision bug

The tolerance of ±0.5 pp is tight enough to catch real regressions but
loose enough to survive minor float-rounding changes.
"""

from __future__ import annotations

import pytest
from scorer import _build_scored_dict, _compute_percentage
from tests.evals.conftest import load_fixture, all_scorer_fixtures, assert_product_schema


SCORE_TOLERANCE = 0.5  # percentage points — fail if deviation exceeds this


# ---------------------------------------------------------------------------
# Parametrised: all scorer fixtures get the same structural checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_id", all_scorer_fixtures())
def test_scorer_output_has_required_keys(fixture_id: str):
    """Every scored product must have the full output schema."""
    f = load_fixture(fixture_id)
    rubric = f["rubric"]
    for product in f["products"]:
        mock_scores = f["mock_llm_scores"][product["name"]]
        result = _build_scored_dict(product, mock_scores, rubric)
        assert "name" in result
        assert "scores" in result
        assert "weighted_total" in result
        assert "max_possible" in result
        assert "percentage" in result
        assert 0.0 <= result["percentage"] <= 100.0


@pytest.mark.parametrize("fixture_id", all_scorer_fixtures())
def test_scorer_community_fields_preserved(fixture_id: str):
    """Community fields from the input product must pass through unchanged."""
    f = load_fixture(fixture_id)
    rubric = f["rubric"]
    for product in f["products"]:
        mock_scores = f["mock_llm_scores"][product["name"]]
        result = _build_scored_dict(product, mock_scores, rubric)
        assert result["mention_count"] == product.get("mention_count")
        assert result["signal_strength"] == product.get("signal_strength")
        if product.get("positive_mentions") is not None:
            assert result["positive_mentions"] == product["positive_mentions"]


# ---------------------------------------------------------------------------
# Earbuds golden percentages
# ---------------------------------------------------------------------------

def test_earbuds_sony_percentage():
    """Sony WF-1000XM5 must score within ±0.5pp of the golden value."""
    f = load_fixture("scorer_earbuds_golden")
    rubric = f["rubric"]
    sony_product  = next(p for p in f["products"] if p["name"] == "Sony WF-1000XM5")
    mock_scores   = f["mock_llm_scores"]["Sony WF-1000XM5"]
    expected      = f["expected_scores"]["Sony WF-1000XM5"]

    result = _build_scored_dict(sony_product, mock_scores, rubric)

    assert abs(result["weighted_total"] - expected["weighted_total"]) < 0.1, (
        f"weighted_total mismatch: {result['weighted_total']} vs {expected['weighted_total']}"
    )
    assert abs(result["percentage"] - expected["percentage"]) <= SCORE_TOLERANCE, (
        f"Sony WF-1000XM5 percentage regression: {result['percentage']:.1f}% "
        f"vs golden {expected['percentage']:.1f}% "
        f"(tolerance ±{SCORE_TOLERANCE}pp)"
    )


def test_earbuds_jabra_percentage():
    """Jabra Elite 5 must score within ±0.5pp of the golden value."""
    f = load_fixture("scorer_earbuds_golden")
    rubric        = f["rubric"]
    jabra_product = next(p for p in f["products"] if p["name"] == "Jabra Elite 5")
    mock_scores   = f["mock_llm_scores"]["Jabra Elite 5"]
    expected      = f["expected_scores"]["Jabra Elite 5"]

    result = _build_scored_dict(jabra_product, mock_scores, rubric)

    assert abs(result["percentage"] - expected["percentage"]) <= SCORE_TOLERANCE, (
        f"Jabra Elite 5 percentage regression: {result['percentage']:.1f}% "
        f"vs golden {expected['percentage']:.1f}%"
    )


def test_earbuds_sony_beats_jabra():
    """Sony must outrank Jabra — if this flips, the rubric or scoring changed."""
    f = load_fixture("scorer_earbuds_golden")
    rubric = f["rubric"]

    scores = {}
    for product in f["products"]:
        mock_scores = f["mock_llm_scores"][product["name"]]
        result = _build_scored_dict(product, mock_scores, rubric)
        scores[product["name"]] = result["percentage"]

    assert scores["Sony WF-1000XM5"] > scores["Jabra Elite 5"], (
        f"Ranking regression: Sony ({scores['Sony WF-1000XM5']:.1f}%) "
        f"should beat Jabra ({scores['Jabra Elite 5']:.1f}%)"
    )


def test_earbuds_score_clamped():
    """Scores outside 0-10 from mock must be clamped."""
    f = load_fixture("scorer_earbuds_golden")
    rubric = f["rubric"]
    product = f["products"][0]

    # Inject out-of-range scores
    bad_scores = [
        {"criterion": "noise_cancellation", "score": 15,  "evidence": "over limit"},
        {"criterion": "sound_quality",      "score": -3,  "evidence": "under limit"},
        {"criterion": "battery_life",       "score": 7.0, "evidence": "normal"},
        {"criterion": "comfort",            "score": 7.0, "evidence": "normal"},
        {"criterion": "price_to_value",     "score": 7.0, "evidence": "normal"},
    ]
    result = _build_scored_dict(product, bad_scores, rubric)
    for s in result["scores"]:
        assert 0.0 <= s["score"] <= 10.0, f"Score {s['score']} not in [0, 10] for {s['criterion']}"


def test_earbuds_missing_criteria_default_to_4():
    """Criteria not returned by LLM default to score=4 (insufficient data)."""
    f = load_fixture("scorer_earbuds_golden")
    rubric = f["rubric"]
    product = f["products"][0]

    result = _build_scored_dict(product, [], rubric)  # no scores from LLM
    for s in result["scores"]:
        assert s["score"] == 4.0, (
            f"Missing criterion {s['criterion']} should default to 4.0, got {s['score']}"
        )


# ---------------------------------------------------------------------------
# Smartphones golden percentages
# ---------------------------------------------------------------------------

def test_smartphones_oneplus_percentage():
    f = load_fixture("scorer_smartphones_golden")
    rubric  = f["rubric"]
    product = next(p for p in f["products"] if p["name"] == "OnePlus 12")
    expected = f["expected_scores"]["OnePlus 12"]

    result = _build_scored_dict(product, f["mock_llm_scores"]["OnePlus 12"], rubric)
    assert abs(result["percentage"] - expected["percentage"]) <= SCORE_TOLERANCE, (
        f"OnePlus 12 regression: {result['percentage']:.1f}% vs {expected['percentage']:.1f}%"
    )


def test_smartphones_pixel_percentage():
    f = load_fixture("scorer_smartphones_golden")
    rubric  = f["rubric"]
    product = next(p for p in f["products"] if p["name"] == "Google Pixel 8 Pro")
    expected = f["expected_scores"]["Google Pixel 8 Pro"]

    result = _build_scored_dict(product, f["mock_llm_scores"]["Google Pixel 8 Pro"], rubric)
    assert abs(result["percentage"] - expected["percentage"]) <= SCORE_TOLERANCE, (
        f"Pixel 8 Pro regression: {result['percentage']:.1f}% vs {expected['percentage']:.1f}%"
    )


# ---------------------------------------------------------------------------
# _compute_percentage precision
# ---------------------------------------------------------------------------

def test_compute_percentage_precision():
    """Decimal precision must eliminate float drift for known values."""
    from scorer import _compute_percentage
    # 107/130 = 0.823076... → 82.3%
    assert _compute_percentage(107.0, 130.0) == 82.3
    # 1/3 → 33.3%
    assert _compute_percentage(1.0, 3.0) == 33.3
    # 0 max → 0%
    assert _compute_percentage(50.0, 0.0) == 0.0
    # Perfect score → 100%
    assert _compute_percentage(100.0, 100.0) == 100.0
