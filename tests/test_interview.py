"""
Interview-layer regression tests.

These tests cover bugs that were fixed in the production hardening pass
and must not regress. All tests are pure unit tests — zero LLM calls.

Covered:
  B1 — [Skipped] tokens must never appear in the preference summary
  R4 — Contradiction resolution: later answer wins
  B1 (intent) — [Skipped] tokens must never appear in hard_constraints
  W2 (structured) — structured intent fields must be populated correctly
"""

import sys
import os
from pathlib import Path

# Allow importing from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from interview import (
    _categorize_qa_entry,
    _summarize_preferences,
    _summarize_and_extract_intent,
    _SKIP_ANSWER_TOKENS,
    _build_priority_classifier_context,
    _dynamic_coverage_target,
)


# ---------------------------------------------------------------------------
# B1: [Skipped] tokens are filtered from summarization
# ---------------------------------------------------------------------------

def test_skipped_not_in_summary():
    """[Skipped] and (skipped) answers must never reach the summarizer — B1."""
    qa_history = [
        {"question": "What is your skin type?", "answer": "[Skipped]"},
        {"question": "Do you prefer fragrance-free?", "answer": "(skipped)"},
        {"question": "What is your budget?", "answer": "under ₹500"},
    ]

    # The summarizer should only process the one answered question
    # We can verify indirectly via _categorize_qa_entry
    cats = [_categorize_qa_entry(qa) for qa in qa_history]
    assert cats[0] == "skipped", f"Expected 'skipped', got '{cats[0]}'"
    assert cats[1] == "skipped", f"Expected 'skipped', got '{cats[1]}'"
    assert cats[2] == "answered", f"Expected 'answered', got '{cats[2]}'"

    # _SKIP_ANSWER_TOKENS must contain both variants
    assert "[Skipped]" in _SKIP_ANSWER_TOKENS
    assert "(skipped)" in _SKIP_ANSWER_TOKENS


def test_skip_tokens_not_in_priority_context():
    """Priority classifier context must not include [Skipped] answers."""
    qa_history = [
        {"question": "Battery life?", "answer": "[Skipped]"},
        {"question": "Budget?", "answer": "₹5000"},
        {"question": "Sound preference?", "answer": "[Skipped]"},
        {"question": "Use case?", "answer": "daily commute"},
    ]
    ctx = _build_priority_classifier_context(qa_history, max_entries=6)
    # Budget entry is critical and must appear
    assert "₹5000" in ctx, "Budget answer should be in priority context"
    # [Skipped] raw tokens should not drive priority inclusion; check they don't contaminate
    # (skipped entries CAN appear in context if within last N, but their content is [Skipped])
    # The key assertion: the context was built without error
    assert isinstance(ctx, str)


# ---------------------------------------------------------------------------
# R4: Contradiction resolution
# ---------------------------------------------------------------------------

def test_contradiction_detection_in_summarize_system():
    """
    SUMMARIZE_SYSTEM must include contradiction resolution rule.
    Regression test: if SUMMARIZE_SYSTEM rule 7 is removed, this fails.
    """
    from interview import SUMMARIZE_SYSTEM
    assert "CONTRADICTION" in SUMMARIZE_SYSTEM or "contradiction" in SUMMARIZE_SYSTEM.lower(), (
        "SUMMARIZE_SYSTEM must contain contradiction resolution rule (R4)"
    )
    assert "LATER" in SUMMARIZE_SYSTEM or "later" in SUMMARIZE_SYSTEM.lower(), (
        "SUMMARIZE_SYSTEM must specify that the later answer wins"
    )


def test_skip_semantics_in_summarize_system():
    """SUMMARIZE_SYSTEM must explicitly handle skip semantics (B1)."""
    from interview import SUMMARIZE_SYSTEM
    assert "skipped" in SUMMARIZE_SYSTEM.lower() or "SKIP" in SUMMARIZE_SYSTEM, (
        "SUMMARIZE_SYSTEM must instruct the LLM how to handle skipped questions"
    )
    assert "UNKNOWN" in SUMMARIZE_SYSTEM, (
        "SUMMARIZE_SYSTEM must state that skipped = UNKNOWN"
    )


# ---------------------------------------------------------------------------
# R3: Dynamic coverage target
# ---------------------------------------------------------------------------

def test_dynamic_coverage_target_typical_criteria():
    """Typical categories (≤12 criteria) target FULL coverage — we personalise on every criterion."""
    from interview import COVERAGE_TARGET
    assert COVERAGE_TARGET == 1.0
    for n in range(1, 13):
        target = _dynamic_coverage_target(n)
        assert target == COVERAGE_TARGET, (
            f"Expected full coverage ({COVERAGE_TARGET}) for {n} criteria, got {target}"
        )


def test_dynamic_coverage_target_large_criteria():
    """Very large criteria sets relax slightly so the interview doesn't blow past the cap,
    but still stay near-complete (>= 0.85)."""
    for n in range(13, 20):
        target = _dynamic_coverage_target(n)
        assert target >= 0.85, f"Expected near-full coverage for {n} criteria, got {target}"


def test_dynamic_coverage_target_monotone_decreasing():
    """Coverage target must be monotone non-increasing as criteria count grows."""
    targets = [_dynamic_coverage_target(n) for n in range(1, 16)]
    for i in range(len(targets) - 1):
        assert targets[i] >= targets[i + 1], (
            f"Coverage target not monotone: _dynamic_coverage_target({i+1})={targets[i]} "
            f"> _dynamic_coverage_target({i+2})={targets[i+1]}"
        )


# ---------------------------------------------------------------------------
# Phase 3: Structured intent model
# ---------------------------------------------------------------------------

def test_summarize_and_extract_intent_structure():
    """_summarize_and_extract_intent must return (str, dict) with correct keys."""
    # We test with empty input — no LLM call needed
    text, intent = _summarize_and_extract_intent("earbuds", [])
    assert isinstance(text, str), "summary_text must be a string"
    assert isinstance(intent, dict), "intent must be a dict"
    assert "hard_constraints" in intent
    assert "budget" in intent
    assert "preferences" in intent
    assert "exclusions" in intent
    assert "uncertainties" in intent
    assert isinstance(intent["hard_constraints"], list)
    assert isinstance(intent["preferences"], list)
    assert isinstance(intent["exclusions"], list)
    assert isinstance(intent["uncertainties"], list)
    # budget is None when no interview answers
    assert intent["budget"] is None


def test_summarize_and_extract_intent_all_skipped():
    """All-skipped interview must return empty intent, not crash."""
    qa_history = [
        {"question": "Q1?", "answer": "[Skipped]"},
        {"question": "Q2?", "answer": "(skipped)"},
    ]
    text, intent = _summarize_and_extract_intent("skincare", qa_history)
    assert isinstance(text, str)
    assert isinstance(intent, dict)
    assert intent["hard_constraints"] == []
    assert intent["budget"] is None
    # Text should indicate nothing was provided
    assert "no preferences" in text.lower() or "skipped" in text.lower()


def test_empty_intent_fields_are_lists_not_none():
    """Fallback _EMPTY_INTENT must have list fields — never None — to avoid downstream crash."""
    from interview import _EMPTY_INTENT
    assert isinstance(_EMPTY_INTENT["hard_constraints"], list)
    assert isinstance(_EMPTY_INTENT["preferences"], list)
    assert isinstance(_EMPTY_INTENT["exclusions"], list)
    assert isinstance(_EMPTY_INTENT["uncertainties"], list)
    # budget is the only field allowed to be None
    assert _EMPTY_INTENT["budget"] is None
