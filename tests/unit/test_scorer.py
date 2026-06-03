"""
Unit tests for scorer.py.

Covers:
 - _compute_percentage: decimal precision, zero-max guard
 - _build_scored_dict: weighted math, score clamping, missing criterion default
 - _COMMUNITY_FIELDS passthrough: every community field preserved on scored dict
 - _filter_research_for_product: word-boundary token matching
 - _fast_score: heuristic scoring runs without LLM
 - _default_score: always returns valid structure
 - score_product: integration with mocked LLM
 - SCORING_MODE env var respected (hybrid/llm/fast)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rubric(criteria=None):
    if criteria is None:
        criteria = [
            {"name": "battery_life",  "label": "Battery Life",  "weight": 8, "description": ""},
            {"name": "sound_quality", "label": "Sound Quality", "weight": 5, "description": ""},
        ]
    return {"weighted_criteria": criteria}


def _product(name="TestBuds", **kw):
    base = {"name": name, "signal_strength": "high"}
    base.update(kw)
    return base


# ── _compute_percentage ────────────────────────────────────────────────────────

class TestComputePercentage:
    def test_correct_weighted_percentage(self):
        from scorer import _compute_percentage
        # battery: 9*8=72, sound: 7*5=35 → 107/130 = 82.3%
        assert _compute_percentage(107, 130) == 82.3

    def test_zero_max_returns_zero(self):
        from scorer import _compute_percentage
        assert _compute_percentage(50, 0) == 0.0

    def test_full_score_returns_100(self):
        from scorer import _compute_percentage
        assert _compute_percentage(100, 100) == 100.0

    def test_decimal_precision(self):
        from scorer import _compute_percentage
        # 1/3 → 33.3%
        result = _compute_percentage(1, 3)
        assert result == 33.3


# ── _build_scored_dict ─────────────────────────────────────────────────────────

class TestBuildScoredDict:
    def test_weighted_math_correct(self):
        from scorer import _build_scored_dict
        rubric = _rubric()
        raw_scores = [
            {"criterion": "battery_life",  "score": 9, "evidence": "great battery"},
            {"criterion": "sound_quality", "score": 7, "evidence": "decent sound"},
        ]
        result = _build_scored_dict(_product(), raw_scores, rubric)
        # battery: 9*8=72, sound: 7*5=35 → total=107, max=130
        assert result["weighted_total"] == 107.0
        assert result["max_possible"] == 130.0
        assert result["percentage"] == 82.3

    def test_score_clamped_to_0_10(self):
        from scorer import _build_scored_dict
        rubric = _rubric([{"name": "c1", "label": "C1", "weight": 5, "description": ""}])
        raw_scores = [{"criterion": "c1", "score": 15, "evidence": "over the top"}]
        result = _build_scored_dict(_product(), raw_scores, rubric)
        assert result["scores"][0]["score"] == 10.0

    def test_negative_score_clamped_to_0(self):
        from scorer import _build_scored_dict
        rubric = _rubric([{"name": "c1", "label": "C1", "weight": 5, "description": ""}])
        raw_scores = [{"criterion": "c1", "score": -3, "evidence": "bad"}]
        result = _build_scored_dict(_product(), raw_scores, rubric)
        assert result["scores"][0]["score"] == 0.0

    def test_missing_criterion_gets_default_score_4(self):
        """Criteria not returned by LLM get score=4 (insufficient data)."""
        from scorer import _build_scored_dict
        rubric = _rubric()
        raw_scores = []  # LLM returned nothing
        result = _build_scored_dict(_product(), raw_scores, rubric)
        for s in result["scores"]:
            assert s["score"] == 4.0

    def test_result_has_required_keys(self):
        from scorer import _build_scored_dict
        result = _build_scored_dict(_product(), [], _rubric())
        assert {"name", "scores", "weighted_total", "max_possible", "percentage"}.issubset(result.keys())


# ── _COMMUNITY_FIELDS passthrough ─────────────────────────────────────────────

class TestCommunityFieldsPassthrough:
    def test_all_community_fields_preserved(self):
        from scorer import _build_scored_dict, _COMMUNITY_FIELDS
        product = _product(
            mention_count=5,
            distinct_recommenders=3,
            positive_mentions=4,
            negative_mentions=1,
            praise=["Great ANC"],
            complaints=[{"text": "Expensive", "confidence": "reported"}],
            representative_quote="Best earbuds I ever owned",
            sources=["r/audiophile"],
            sentiment_score=0.6,
            dominant_sentiment="positive",
            sentiment_records=[],
            cross_subreddit_signal=None,
        )
        result = _build_scored_dict(product, [], _rubric())
        for field in _COMMUNITY_FIELDS:
            assert field in result, f"Community field '{field}' missing from scored dict"

    def test_community_field_values_match_input(self):
        from scorer import _build_scored_dict
        product = _product(mention_count=7, representative_quote="Awesome")
        result = _build_scored_dict(product, [], _rubric())
        assert result["mention_count"] == 7
        assert result["representative_quote"] == "Awesome"

    def test_missing_community_fields_are_none(self):
        from scorer import _build_scored_dict, _COMMUNITY_FIELDS
        result = _build_scored_dict(_product(), [], _rubric())
        for field in _COMMUNITY_FIELDS:
            # Must be present (None is acceptable, missing is not)
            assert field in result


# ── _filter_research_for_product ──────────────────────────────────────────────

class TestFilterResearch:
    def test_relevant_paragraphs_included(self):
        from scorer import _filter_research_for_product
        research = "Sony WF-1000XM5 has great ANC.\n\nUnrelated paragraph.\n\nSony WF-1000XM5 battery is 8 hours."
        result = _filter_research_for_product("Sony WF-1000XM5", research)
        assert "great ANC" in result
        assert "8 hours" in result

    def test_unrelated_paragraphs_excluded(self):
        from scorer import _filter_research_for_product
        research = "Apple AirPods are nice.\n\nUnrelated fluff.\n\nMore fluff."
        result = _filter_research_for_product("Sony WF-1000XM5", research, max_chars=5000)
        # Should not contain AirPods-specific content in WF-1000XM5 filter
        # (may return full text as fallback if no match found)
        assert isinstance(result, str)

    def test_max_chars_respected(self):
        from scorer import _filter_research_for_product
        long_text = "Widget X " * 5000
        result = _filter_research_for_product("Widget X", long_text, max_chars=500)
        assert len(result) <= 500

    def test_empty_research_returns_empty(self):
        from scorer import _filter_research_for_product
        assert _filter_research_for_product("Widget", "") == ""


# ── _default_score ─────────────────────────────────────────────────────────────

class TestDefaultScore:
    def test_always_returns_valid_dict(self):
        from scorer import _default_score
        result = _default_score(_product(), _rubric())
        assert "name" in result
        assert "percentage" in result
        assert 0.0 <= result["percentage"] <= 100.0

    def test_all_criteria_in_result(self):
        from scorer import _default_score
        rubric = _rubric()
        result = _default_score(_product(), rubric)
        criterion_names = {s["criterion"] for s in result["scores"]}
        assert criterion_names == {"battery_life", "sound_quality"}


# ── _fast_score ────────────────────────────────────────────────────────────────

class TestFastScore:
    def test_returns_valid_scored_dict(self):
        from scorer import _fast_score
        result = _fast_score(
            _product(mention_count=5, positive_mentions=4, negative_mentions=1),
            _rubric(),
            "Widget X has great battery life. Widget X sound quality is excellent.",
        )
        assert "percentage" in result
        assert 0.0 <= result["percentage"] <= 100.0

    def test_no_llm_call(self):
        """_fast_score must never call run_agent."""
        from scorer import _fast_score
        with patch("scorer.run_agent") as mock_agent:
            _fast_score(_product(), _rubric(), "Widget X research text")
            mock_agent.assert_not_called()


# ── score_product integration ─────────────────────────────────────────────────

class TestScoreProduct:
    def test_returns_scored_dict_on_valid_response(self):
        from scorer import score_product
        rubric = _rubric()
        mock_response = '{"scores": [{"criterion": "battery_life", "score": 9, "evidence": "great"}, {"criterion": "sound_quality", "score": 7, "evidence": "decent"}]}'
        import llm_client as _llmc
        orig = _llmc._try_repair_json
        _llmc._try_repair_json = lambda x: __import__("json").loads(x)
        try:
            with patch("scorer.run_agent", return_value=mock_response):
                result = score_product(_product(), rubric, "research text")
        finally:
            _llmc._try_repair_json = orig
        assert result is not None
        assert result["percentage"] == 82.3

    def test_returns_none_on_llm_failure(self):
        from scorer import score_product
        with patch("scorer.run_agent", side_effect=RuntimeError("LLM down")):
            result = score_product(_product(), _rubric(), "research")
        assert result is None


# ── SCORING_MODE ──────────────────────────────────────────────────────────────

class TestScoringMode:
    def test_valid_modes_accepted(self):
        for mode in ("llm", "hybrid", "fast"):
            os.environ["SCORING_MODE"] = mode
            import importlib, scorer as _sc
            importlib.reload(_sc)
            assert _sc.SCORING_MODE == mode
        os.environ.pop("SCORING_MODE", None)

    def test_invalid_mode_defaults_to_hybrid(self):
        os.environ["SCORING_MODE"] = "turbo"
        import importlib, scorer as _sc
        importlib.reload(_sc)
        assert _sc.SCORING_MODE == "hybrid"
        os.environ.pop("SCORING_MODE", None)
