"""
Unit tests for rubric.py.

Covers:
 - _normalize_weights: sum normalised correctly, edge cases
 - _default_weight: always returns valid struct
 - generate_rubric: mocked LLM, missing criteria filled with defaults
 - fill_criterion_gaps: skipped when defaulted < 2, applies inferred weights
 - _extract_criterion_relevant_snippet: keyword matching, max_chars cap
 - _restore_manual_weights: preserves hand-edited weights across rubric regen
 - rubric_path / save_rubric / load_rubric: round-trip (tmp dir)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _criteria(names=("battery_life", "sound_quality", "comfort")):
    return [
        {"name": n, "label": n.replace("_", " ").title(), "description": ""}
        for n in names
    ]


def _rubric_with_defaults(criteria_names):
    return {
        "weighted_criteria": [
            {
                "name": n,
                "label": n.replace("_", " ").title(),
                "weight": 5,
                "rationale": "Default weight - not addressed in interview",
                "source": "default",
            }
            for n in criteria_names
        ]
    }


def _rubric_with_manual(criteria_names, manual_weight=9):
    wc = []
    for n in criteria_names:
        is_manual = n == criteria_names[0]
        wc.append({
            "name": n,
            "label": n.replace("_", " ").title(),
            "weight": manual_weight if is_manual else 5,
            "rationale": "Manually set" if is_manual else "Default weight - not addressed in interview",
            "source": "manual" if is_manual else "default",
        })
    return {"weighted_criteria": wc}


# ── _normalize_weights ────────────────────────────────────────────────────────

class TestNormalizeWeights:
    def test_normalized_weights_sum_to_1(self):
        """_normalize_weights adds a normalized_weight field (0-1 fraction)."""
        from rubric import _normalize_weights
        criteria = [
            {"name": "a", "weight": 2},
            {"name": "b", "weight": 3},
            {"name": "c", "weight": 5},
        ]
        _normalize_weights(criteria)
        total = sum(c["normalized_weight"] for c in criteria)
        assert abs(total - 1.0) < 0.001

    def test_normalized_proportions_correct(self):
        from rubric import _normalize_weights
        criteria = [{"name": "a", "weight": 1}, {"name": "b", "weight": 3}]
        _normalize_weights(criteria)
        assert abs(criteria[0]["normalized_weight"] - 0.25) < 0.001
        assert abs(criteria[1]["normalized_weight"] - 0.75) < 0.001

    def test_equal_weights_get_equal_fractions(self):
        from rubric import _normalize_weights
        criteria = [{"name": "a", "weight": 5}, {"name": "b", "weight": 5}]
        _normalize_weights(criteria)
        assert abs(criteria[0]["normalized_weight"] - 0.5) < 0.001

    def test_zero_weight_handled(self):
        from rubric import _normalize_weights
        criteria = [{"name": "a", "weight": 0}, {"name": "b", "weight": 0}]
        # Should not raise; normalized_weight field added
        _normalize_weights(criteria)
        for c in criteria:
            assert "normalized_weight" in c


# ── _default_weight ────────────────────────────────────────────────────────────

class TestDefaultWeight:
    def test_returns_valid_structure(self):
        from rubric import _default_weight
        c = {"name": "battery_life", "label": "Battery Life", "description": ""}
        result = _default_weight(c)
        assert result["name"] == "battery_life"
        assert isinstance(result["weight"], (int, float))
        assert "rationale" in result
        assert result.get("source") == "default"

    def test_weight_in_valid_range(self):
        from rubric import _default_weight
        c = {"name": "build_quality", "label": "Build Quality", "description": ""}
        result = _default_weight(c)
        assert 0 <= result["weight"] <= 10


# ── generate_rubric ────────────────────────────────────────────────────────────

class TestGenerateRubric:
    def test_all_criteria_present_in_output(self):
        from rubric import generate_rubric
        import llm_client as _llmc
        orig = _llmc._try_repair_json
        _llmc._try_repair_json = lambda x: __import__("json").loads(x)
        criteria = _criteria(("battery_life", "sound_quality"))
        mock_response = json.dumps({"weighted_criteria": [
            {"name": "battery_life",  "label": "Battery Life",  "weight": 8, "rationale": "user cares"},
            {"name": "sound_quality", "label": "Sound Quality", "weight": 6, "rationale": "user cares"},
        ]})
        try:
            with patch("rubric.run_agent", return_value=mock_response):
                rubric = generate_rubric("electronics/earbuds", criteria, {"preferences_summary": "needs good battery"})
        finally:
            _llmc._try_repair_json = orig
        names = {c["name"] for c in rubric["weighted_criteria"]}
        assert "battery_life" in names
        assert "sound_quality" in names

    def test_missing_criterion_filled_with_default(self):
        """LLM returned only one criterion; the other must be filled with defaults."""
        from rubric import generate_rubric
        import llm_client as _llmc
        orig = _llmc._try_repair_json
        _llmc._try_repair_json = lambda x: __import__("json").loads(x)
        criteria = _criteria(("battery_life", "sound_quality"))
        mock_response = json.dumps({"weighted_criteria": [
            {"name": "battery_life", "label": "Battery Life", "weight": 8, "rationale": "user cares"},
        ]})
        try:
            with patch("rubric.run_agent", return_value=mock_response):
                rubric = generate_rubric("electronics/earbuds", criteria, {})
        finally:
            _llmc._try_repair_json = orig
        names = {c["name"] for c in rubric["weighted_criteria"]}
        assert "sound_quality" in names  # must be added as default

    def test_bad_json_falls_back_to_defaults(self):
        """JSON parse failure → defaults for all criteria (run_agent errors propagate)."""
        from rubric import generate_rubric
        with patch("rubric.run_agent", return_value="not valid json {{{}}}"):
            rubric = generate_rubric("electronics/earbuds", _criteria(), {})
        assert len(rubric["weighted_criteria"]) == len(_criteria())
        for c in rubric["weighted_criteria"]:
            assert isinstance(c["weight"], (int, float))

    def test_qa_skipped_when_preferences_summary_rich(self):
        """When preferences_summary >= 150 chars, Q&A JSON must NOT appear in prompt."""
        from rubric import generate_rubric
        captured_prompt = {}
        def mock_agent(name, user_prompt="", system=""):
            captured_prompt["prompt"] = user_prompt
            return json.dumps({"weighted_criteria": []})
        with patch("rubric.run_agent", side_effect=mock_agent):
            generate_rubric(
                "electronics/earbuds",
                _criteria(),
                {
                    "preferences_summary": "x" * 200,  # rich summary
                    "interview": [{"question": "Q1", "answer": "A1"}],
                },
            )
        prompt = captured_prompt.get("prompt", "")
        assert "Full interview Q&A" not in prompt

    def test_qa_included_when_preferences_summary_short(self):
        """When preferences_summary < 150 chars, Q&A JSON must appear in prompt."""
        from rubric import generate_rubric
        captured_prompt = {}
        def mock_agent(name, user_prompt="", system=""):
            captured_prompt["prompt"] = user_prompt
            return json.dumps({"weighted_criteria": []})
        with patch("rubric.run_agent", side_effect=mock_agent):
            generate_rubric(
                "electronics/earbuds",
                _criteria(),
                {
                    "preferences_summary": "short",
                    "interview": [{"question": "Q1", "answer": "A1"}],
                },
            )
        prompt = captured_prompt.get("prompt", "")
        assert "Full interview Q&A" in prompt


# ── fill_criterion_gaps ────────────────────────────────────────────────────────

class TestFillCriterionGaps:
    def test_skipped_when_fewer_than_2_defaults(self):
        """One defaulted criterion doesn't justify a gap-fill LLM call."""
        from rubric import fill_criterion_gaps
        rubric = {
            "weighted_criteria": [
                {"name": "battery_life",  "weight": 8, "rationale": "user mentioned it", "source": "llm"},
                {"name": "sound_quality", "weight": 5, "rationale": "Default weight - not addressed in interview", "source": "default"},
            ]
        }
        with patch("rubric.run_agent") as mock_agent:
            fill_criterion_gaps(rubric, "electronics/earbuds", {}, "research text")
            mock_agent.assert_not_called()

    def test_called_when_2_or_more_defaults(self):
        from rubric import fill_criterion_gaps
        import llm_client as _llmc
        orig = _llmc.safe_json_loads if hasattr(_llmc, "safe_json_loads") else None
        rubric = _rubric_with_defaults(["battery_life", "sound_quality", "comfort"])
        mock_response = json.dumps({"inferred_weights": [
            {"name": "battery_life",  "weight": 7},
            {"name": "sound_quality", "weight": 6},
            {"name": "comfort",       "weight": 5},
        ]})
        with patch("rubric.run_agent", return_value=mock_response):
            result = fill_criterion_gaps(rubric, "electronics/earbuds", {}, "research text")
        # Weights should be updated from defaults (5) to inferred values
        by_name = {c["name"]: c for c in result["weighted_criteria"]}
        assert by_name["battery_life"]["weight"] == 7

    def test_returns_rubric_unchanged_on_llm_failure(self):
        from rubric import fill_criterion_gaps
        rubric = _rubric_with_defaults(["battery_life", "sound_quality"])
        original_weights = {c["name"]: c["weight"] for c in rubric["weighted_criteria"]}
        with patch("rubric.run_agent", side_effect=RuntimeError("LLM down")):
            result = fill_criterion_gaps(rubric, "electronics/earbuds", {}, "text")
        for c in result["weighted_criteria"]:
            assert c["weight"] == original_weights[c["name"]]


# ── _restore_manual_weights ────────────────────────────────────────────────────

class TestRestoreManualWeights:
    def test_manual_weights_preserved_in_gap_fill(self):
        """A criterion marked source='manual' must not be overwritten by gap-fill."""
        from rubric import fill_criterion_gaps
        rubric = {
            "weighted_criteria": [
                {"name": "battery_life",  "label": "Battery Life",  "weight": 9, "rationale": "Manually set", "source": "manual"},
                {"name": "sound_quality", "label": "Sound Quality", "weight": 5, "rationale": "Default weight - not addressed in interview", "source": "default"},
                {"name": "comfort",       "label": "Comfort",       "weight": 5, "rationale": "Default weight - not addressed in interview", "source": "default"},
            ]
        }
        mock_response = json.dumps({"inferred_weights": [
            {"name": "battery_life",  "weight": 3},  # tries to overwrite manual
            {"name": "sound_quality", "weight": 6},
            {"name": "comfort",       "weight": 4},
        ]})
        with patch("rubric.run_agent", return_value=mock_response):
            result = fill_criterion_gaps(rubric, "electronics/earbuds", {}, "text")
        by_name = {c["name"]: c for c in result["weighted_criteria"]}
        # Manual weight must be preserved
        assert by_name["battery_life"]["weight"] == 9


# ── _extract_criterion_relevant_snippet ───────────────────────────────────────

class TestExtractCriterionSnippet:
    def test_relevant_text_extracted(self):
        from rubric import _extract_criterion_relevant_snippet
        criteria = [{"name": "battery_life", "label": "Battery Life", "description": "how long per charge"}]
        text = "The Sony WF-1000XM5 has great battery life. Completely unrelated paragraph. Another battery life discussion."
        result = _extract_criterion_relevant_snippet(text, criteria, max_chars=5000)
        assert "battery" in result.lower()

    def test_max_chars_respected(self):
        from rubric import _extract_criterion_relevant_snippet
        criteria = [{"name": "battery_life", "label": "Battery Life", "description": ""}]
        text = "battery life " * 1000
        result = _extract_criterion_relevant_snippet(text, criteria, max_chars=100)
        assert len(result) <= 100

    def test_empty_text_returns_placeholder(self):
        from rubric import _extract_criterion_relevant_snippet
        criteria = [{"name": "battery_life", "label": "Battery Life", "description": ""}]
        result = _extract_criterion_relevant_snippet("", criteria)
        assert isinstance(result, str)  # "(no research yet)" or "" — either is valid


# ── save_rubric / load_rubric round-trip ──────────────────────────────────────

class TestRubricPersistence:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        import rubric as _rubric_mod
        # Redirect rubric storage to tmp directory
        monkeypatch.setattr(_rubric_mod, "rubric_path",
                            lambda cat: tmp_path / (cat.replace("/", "_") + ".json"))
        rubric = {
            "weighted_criteria": [
                {"name": "battery_life", "label": "Battery Life", "weight": 8, "rationale": "test"},
            ]
        }
        _rubric_mod.save_rubric("electronics/earbuds", rubric)
        loaded = _rubric_mod.load_rubric("electronics/earbuds")
        assert loaded is not None
        assert loaded["weighted_criteria"][0]["weight"] == 8

    def test_load_nonexistent_returns_none(self, tmp_path, monkeypatch):
        import rubric as _rubric_mod
        monkeypatch.setattr(_rubric_mod, "rubric_path",
                            lambda cat: tmp_path / (cat.replace("/", "_") + ".json"))
        result = _rubric_mod.load_rubric("nonexistent/category")
        assert result is None
