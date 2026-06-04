"""
Golden-file tests for LLM-output SHAPE handling across the pipeline's parse boundaries.

Gap #3 defense: if a provider updates its model and starts returning malformed JSON —
markdown-wrapped, missing keys, extra criteria, non-numeric weights, wrong types — the
parse/normalize layer in each module must still produce a canonical, downstream-safe
shape (or a clean fallback) and never crash.

These tests feed recorded/synthetic raw LLM strings through the real parse code by
monkeypatching `run_agent` at each module boundary. No network, no API keys consumed.

Covered boundaries:
  - rubric.generate_rubric          (rubric_generator agent)
  - interview.generate_next_question (interview_questioner agent)
  - interview.process_message        (interview_classifier agent)
  - interview._summarize_and_extract_intent (preference_summarizer agent)
  - cross_validate._validate_result / _majority_sentiment / _sentiments_are_split (pure)
"""

from __future__ import annotations

import json
import pytest

# conftest.py sets dummy API keys + sys.path; import after that side effect.
from tests.evals.conftest import load_fixture  # noqa: F401  (ensures conftest import order)

import rubric as rubric_mod
import interview as interview_mod
import cross_validate as cv_mod


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_CRITERIA = [
    {"name": "sound_quality",      "label": "Sound Quality",      "description": "audio fidelity"},
    {"name": "battery_life",       "label": "Battery Life",       "description": "runtime"},
    {"name": "noise_cancellation", "label": "Noise Cancellation", "description": "ANC depth"},
]

_PROFILE = {
    "preferences_summary": "User prioritises ANC for a noisy commute and wants all-day battery.",
    "interview": [
        {"question": "What matters most?", "answer": "Noise cancelling for the train."},
        {"question": "Battery?", "answer": "All day."},
    ],
    "intent": {"hard_constraints": ["must have ANC"], "exclusions": [], "budget": "under 20000",
               "preferences": ["long battery"], "uncertainties": []},
    "last_updated": "2026-06-04",
}


def _assert_canonical_rubric(rubric: dict):
    """Every rubric must satisfy the downstream contract regardless of LLM output."""
    assert isinstance(rubric, dict)
    assert rubric.get("category")
    wc = rubric.get("weighted_criteria")
    assert isinstance(wc, list) and len(wc) == len(_CRITERIA), "must emit exactly one entry per input criterion"

    names = {c["name"] for c in wc}
    assert names == {c["name"] for c in _CRITERIA}, "every input criterion must be present, none invented"

    total_norm = 0.0
    for c in wc:
        assert set(c) >= {"name", "label", "weight", "rationale", "normalized_weight", "source"}
        assert 0.0 <= c["weight"] <= 10.0, f"weight out of range: {c['weight']}"
        assert isinstance(c["weight"], float)
        assert 0.0 <= c["normalized_weight"] <= 1.0
        assert c["source"] in ("llm", "default")
        total_norm += c["normalized_weight"]
    assert abs(total_norm - 1.0) < 0.01, f"normalized weights must sum to ~1.0, got {total_norm}"


# ──────────────────────────────────────────────────────────────────────────────
# rubric.generate_rubric — parse → validate → normalize boundary
# ──────────────────────────────────────────────────────────────────────────────

# (id, raw_llm_string) — each is a different way a provider can misbehave.
_RUBRIC_RAW_CASES = [
    (
        "clean",
        json.dumps({"weighted_criteria": [
            {"name": "sound_quality", "label": "Sound Quality", "weight": 6, "rationale": "ok"},
            {"name": "battery_life", "label": "Battery Life", "weight": 8, "rationale": "all day"},
            {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 10, "rationale": "commute"},
        ]}),
    ),
    (
        "markdown_wrapped",
        "```json\n" + json.dumps({"weighted_criteria": [
            {"name": "sound_quality", "label": "Sound Quality", "weight": 5, "rationale": "x"},
            {"name": "battery_life", "label": "Battery Life", "weight": 7, "rationale": "x"},
            {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 9, "rationale": "x"},
        ]}) + "\n```",
    ),
    (
        "missing_one_criterion",  # LLM omits battery_life → must default-fill it
        json.dumps({"weighted_criteria": [
            {"name": "sound_quality", "label": "Sound Quality", "weight": 6, "rationale": "x"},
            {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 10, "rationale": "x"},
        ]}),
    ),
    (
        "extra_invented_criterion",  # LLM hallucinates 'magic_factor' → must be dropped
        json.dumps({"weighted_criteria": [
            {"name": "sound_quality", "label": "Sound Quality", "weight": 6, "rationale": "x"},
            {"name": "battery_life", "label": "Battery Life", "weight": 7, "rationale": "x"},
            {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 9, "rationale": "x"},
            {"name": "magic_factor", "label": "Magic", "weight": 10, "rationale": "made up"},
        ]}),
    ),
    (
        "weight_out_of_range",  # 15 and -3 must clamp to 10 and 0
        json.dumps({"weighted_criteria": [
            {"name": "sound_quality", "label": "Sound Quality", "weight": 15, "rationale": "x"},
            {"name": "battery_life", "label": "Battery Life", "weight": -3, "rationale": "x"},
            {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 9, "rationale": "x"},
        ]}),
    ),
    (
        "non_numeric_weight",  # string weight → entry invalid → default-filled
        json.dumps({"weighted_criteria": [
            {"name": "sound_quality", "label": "Sound Quality", "weight": "high", "rationale": "x"},
            {"name": "battery_life", "label": "Battery Life", "weight": 7, "rationale": "x"},
            {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 9, "rationale": "x"},
        ]}),
    ),
    (
        "malformed_json",  # total garbage → full default fallback
        "I think sound quality matters a lot, here are the weights but no JSON",
    ),
    (
        "trailing_comma_and_prose",  # repairable JSON with trailing comma + lead-in text
        "Sure! Here you go:\n{\"weighted_criteria\": ["
        "{\"name\": \"sound_quality\", \"label\": \"Sound Quality\", \"weight\": 6, \"rationale\": \"x\"},"
        "{\"name\": \"battery_life\", \"label\": \"Battery Life\", \"weight\": 7, \"rationale\": \"x\"},"
        "{\"name\": \"noise_cancellation\", \"label\": \"Noise Cancellation\", \"weight\": 9, \"rationale\": \"x\"},"
        "]}",
    ),
]


@pytest.mark.parametrize("case_id,raw", _RUBRIC_RAW_CASES, ids=[c[0] for c in _RUBRIC_RAW_CASES])
def test_rubric_shape_survives_llm_output(case_id, raw, monkeypatch):
    monkeypatch.setattr(rubric_mod, "run_agent", lambda *a, **k: raw)
    monkeypatch.setattr(rubric_mod, "save_rubric", lambda *a, **k: None)  # no disk write

    result = rubric_mod.generate_rubric("electronics/earbuds", _CRITERIA, _PROFILE)
    _assert_canonical_rubric(result)


def test_rubric_missing_criterion_is_defaulted(monkeypatch):
    raw = json.dumps({"weighted_criteria": [
        {"name": "sound_quality", "label": "Sound Quality", "weight": 6, "rationale": "x"},
        {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 10, "rationale": "x"},
    ]})
    monkeypatch.setattr(rubric_mod, "run_agent", lambda *a, **k: raw)
    monkeypatch.setattr(rubric_mod, "save_rubric", lambda *a, **k: None)

    result = rubric_mod.generate_rubric("electronics/earbuds", _CRITERIA, _PROFILE)
    battery = next(c for c in result["weighted_criteria"] if c["name"] == "battery_life")
    assert battery["source"] == "default", "omitted criterion must be marked default, not llm"


def test_rubric_clamps_out_of_range(monkeypatch):
    raw = json.dumps({"weighted_criteria": [
        {"name": "sound_quality", "label": "Sound Quality", "weight": 15, "rationale": "x"},
        {"name": "battery_life", "label": "Battery Life", "weight": -3, "rationale": "x"},
        {"name": "noise_cancellation", "label": "Noise Cancellation", "weight": 9, "rationale": "x"},
    ]})
    monkeypatch.setattr(rubric_mod, "run_agent", lambda *a, **k: raw)
    monkeypatch.setattr(rubric_mod, "save_rubric", lambda *a, **k: None)

    result = rubric_mod.generate_rubric("electronics/earbuds", _CRITERIA, _PROFILE)
    by_name = {c["name"]: c for c in result["weighted_criteria"]}
    assert by_name["sound_quality"]["weight"] == 10.0
    assert by_name["battery_life"]["weight"] == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# interview.generate_next_question
# ──────────────────────────────────────────────────────────────────────────────

_QUESTION_RAW_CASES = [
    ("clean", json.dumps({"question": "What's your budget?", "why_asking": "to filter",
                          "targets_criterion": "price_to_value", "is_done": False})),
    ("markdown", "```json\n" + json.dumps({"question": "ANC important?", "why_asking": "commute",
                                           "targets_criterion": "noise_cancellation", "is_done": False}) + "\n```"),
    ("done_no_question", json.dumps({"question": "", "why_asking": "", "targets_criterion": "", "is_done": True})),
    ("malformed", "no json here at all"),
    ("missing_keys", json.dumps({"question": "Do you game?"})),  # other keys absent → must fill
    ("is_done_string", json.dumps({"question": "", "why_asking": "", "targets_criterion": "", "is_done": "true"})),
]


@pytest.mark.parametrize("case_id,raw", _QUESTION_RAW_CASES, ids=[c[0] for c in _QUESTION_RAW_CASES])
def test_next_question_shape(case_id, raw, monkeypatch):
    monkeypatch.setattr(interview_mod, "run_agent", lambda *a, **k: raw)
    # Non-empty previous_qa (and a budget already given) skips the hardcoded budget-first
    # question so we exercise the real LLM-parse path under test.
    prior = [{"question": "Budget?", "answer": "under 20000", "targets_criterion": "budget"}]
    result = interview_mod.generate_next_question(
        category="electronics/earbuds", criteria=_CRITERIA, previous_qa=prior,
        initial_query="best earbuds under 20000", primary_noun="earbuds",
    )
    assert isinstance(result, dict)
    assert set(result) >= {"question", "why_asking", "targets_criterion", "is_done"}
    assert isinstance(result["question"], str)
    assert isinstance(result["is_done"], bool), "is_done must be coerced to bool"
    assert isinstance(result["targets_criterion"], str)


# ──────────────────────────────────────────────────────────────────────────────
# interview.process_message
# ──────────────────────────────────────────────────────────────────────────────

_VALID_INTENTS = {"ANSWER", "QUESTION", "UNCLEAR", "COMMAND", "MIXED", "SKIP"}

_PROCESS_RAW_CASES = [
    ("answer", json.dumps({"intent": "ANSWER", "confidence": 0.9, "preference_fragment": "loves bass"})),
    ("question", json.dumps({"intent": "QUESTION", "confidence": 0.8, "question_answer": "ANC blocks noise"})),
    ("mixed", json.dumps({"intent": "MIXED", "confidence": 0.7, "preference_fragment": "gaming",
                          "question_answer": "latency is delay"})),
    ("malformed", "garbage non-json"),  # → ANSWER fallback
    ("confidence_string", json.dumps({"intent": "ANSWER", "confidence": "0.6", "preference_fragment": "x"})),
    ("missing_confidence", json.dumps({"intent": "UNCLEAR"})),
]


@pytest.mark.parametrize("case_id,raw", _PROCESS_RAW_CASES, ids=[c[0] for c in _PROCESS_RAW_CASES])
def test_process_message_shape(case_id, raw, monkeypatch):
    monkeypatch.setattr(interview_mod, "run_agent", lambda *a, **k: raw)
    current_q = {"question": "What matters most?", "why_asking": "x", "targets_criterion": "sound_quality"}
    result = interview_mod.process_message(
        category="electronics/earbuds", criteria=_CRITERIA,
        current_question=current_q, message="I want strong bass", qa_history=[],
    )
    assert isinstance(result, dict)
    assert set(result) >= {"intent", "confidence", "preference_fragment",
                           "question_answer", "clarification_question", "command_action"}
    assert isinstance(result["confidence"], float), "confidence must always be a float"
    # Intent is passed through; malformed input must land on the ANSWER fallback.
    if case_id == "malformed":
        assert result["intent"] == "ANSWER"


# ──────────────────────────────────────────────────────────────────────────────
# interview._summarize_and_extract_intent — UserIntent shape
# ──────────────────────────────────────────────────────────────────────────────

_INTENT_RAW_CASES = [
    ("clean", json.dumps({"summary_text": "Wants ANC and battery.",
                          "hard_constraints": ["must have ANC"], "budget": "under 20000",
                          "preferences": ["battery"], "exclusions": [], "uncertainties": []})),
    ("nulls", json.dumps({"summary_text": None, "hard_constraints": None, "budget": None,
                          "preferences": None, "exclusions": None, "uncertainties": None})),
    ("dirty_lists", json.dumps({"summary_text": "x", "hard_constraints": ["  trimmed  ", "", 42, "valid"],
                                "budget": "  ₹20000  ", "preferences": ["a"], "exclusions": [], "uncertainties": []})),
    ("malformed", "not json"),
]


@pytest.mark.parametrize("case_id,raw", _INTENT_RAW_CASES, ids=[c[0] for c in _INTENT_RAW_CASES])
def test_summarize_intent_shape(case_id, raw, monkeypatch):
    monkeypatch.setattr(interview_mod, "run_agent", lambda *a, **k: raw)
    qa = [{"question": "What matters?", "answer": "ANC and battery for my commute."}]
    summary, intent = interview_mod._summarize_and_extract_intent("electronics/earbuds", qa)

    assert isinstance(summary, str)
    assert set(intent) == {"hard_constraints", "budget", "preferences", "exclusions", "uncertainties"}
    for key in ("hard_constraints", "preferences", "exclusions", "uncertainties"):
        assert isinstance(intent[key], list)
        assert all(isinstance(x, str) and x.strip() for x in intent[key]), f"{key} must be clean non-empty strings"
    assert intent["budget"] is None or isinstance(intent["budget"], str)

    if case_id == "dirty_lists":
        # Non-string (42) and empty entries must be filtered; survivors trimmed.
        assert intent["hard_constraints"] == ["trimmed", "valid"]
        assert intent["budget"] == "₹20000"


# ──────────────────────────────────────────────────────────────────────────────
# cross_validate — pure shape/logic functions
# ──────────────────────────────────────────────────────────────────────────────

def test_cross_validate_validate_result():
    valid = {"signal": "split", "explanation": "differs by use case", "context_note": "use-case dependent"}
    # Required-key set is module-defined; a fully-populated valid dict must pass.
    cleaned = cv_mod._validate_result(valid)
    assert cleaned is not None
    assert cleaned["signal"] in {"split", "consistent", "single_source"}

    # Non-dict → None
    assert cv_mod._validate_result("not a dict") is None
    assert cv_mod._validate_result(None) is None
    assert cv_mod._validate_result([1, 2, 3]) is None


def test_cross_validate_invalid_signal_normalised():
    # An unrecognised signal value must be coerced to a safe default, not passed through.
    result = {k: "x" for k in cv_mod._REQUIRED_KEYS}
    result["signal"] = "totally_bogus"
    cleaned = cv_mod._validate_result(result)
    assert cleaned is not None
    assert cleaned["signal"] == "split"


def test_cross_validate_majority_sentiment():
    assert cv_mod._majority_sentiment(["positive", "positive", "negative"]) == "positive"
    assert cv_mod._majority_sentiment(["negative", "negative", "mixed"]) == "negative"
    # Tie-break order: positive > negative > mixed
    assert cv_mod._majority_sentiment(["positive", "negative"]) == "positive"
    # Unknown labels collapse to 'mixed'
    assert cv_mod._majority_sentiment(["weird", "weird"]) == "mixed"
    # Empty input must not crash and must return a valid label (callers filter empties).
    assert cv_mod._majority_sentiment([]) in {"positive", "negative", "mixed"}


def test_cross_validate_split_detection():
    split = {"r/audiophile": ["positive", "positive"], "r/headphones": ["negative", "negative"]}
    assert cv_mod._sentiments_are_split(split) is True

    consistent = {"r/a": ["positive"], "r/b": ["positive"]}
    assert cv_mod._sentiments_are_split(consistent) is False

    # Mixed-only divergence is NOT a split (avoids firing LLM on low-signal data)
    mixed = {"r/a": ["mixed"], "r/b": ["positive"]}
    assert cv_mod._sentiments_are_split(mixed) is False
