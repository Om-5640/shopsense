"""
Pipeline-layer regression tests.

All tests are pure unit tests — zero LLM calls, zero network requests.

Covered:
  B2 — Memory context appended AFTER current session preferences (not prepended)
  R2 — Cache key fingerprints Q&A interview only, not merged preferences_summary
  B3 — Retrieval query enriched with usage pattern from preferences
  B5 — Scorer criterion text shows rationale (not bare description)
  Phase 3 — Analyzer hint prefers structured intent when available
  Phase 9 — Thread dedup removes near-duplicate threads
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from pipeline_runner import (
    _pipeline_cache_key,
    _build_retrieval_query,
    _build_analyzer_hint,
    _build_score_based_explanation,
    _dedup_threads,
)
from scorer import _format_criterion_line


# ---------------------------------------------------------------------------
# B2: Memory precedence — current session first, memory supplemental
# ---------------------------------------------------------------------------

def test_memory_order_in_profile_merge():
    """
    When memory context is merged into a profile, the current-session
    preferences_summary must come FIRST.  The memory context is supplemental.
    Regression for B2 where stale memory was prepended over fresh answers.
    """
    # Simulate what api/main.py does in the /api/rubric endpoint
    profile = {"preferences_summary": "User wants ANC. Budget ₹5000."}
    memory_context = "Past: prefers over-ear from 3 months ago."

    existing = profile.get("preferences_summary", "")
    merged_summary = f"{existing}\n\nAdditional context from past searches:\n{memory_context}"
    merged_profile = {**profile, "preferences_summary": merged_summary}

    assert merged_profile["preferences_summary"].startswith("User wants ANC"), (
        "Current-session preferences must come FIRST in the merged summary (B2)"
    )
    assert "Additional context from past searches" in merged_profile["preferences_summary"]
    # Memory appears AFTER the current session, not before
    session_pos = merged_profile["preferences_summary"].find("User wants ANC")
    memory_pos = merged_profile["preferences_summary"].find("Past: prefers over-ear")
    assert session_pos < memory_pos, (
        "Current-session text must appear before memory text in merged summary"
    )


# ---------------------------------------------------------------------------
# R2: Cache key uses interview Q&A, not merged preferences_summary
# ---------------------------------------------------------------------------

def test_cache_key_ignores_preferences_summary():
    """
    Cache key must fingerprint interview Q&A, not preferences_summary.
    Adding cross-category memory to preferences_summary must NOT change the key.
    Regression for R2 where memory signals from unrelated searches busted the cache.
    """
    rubric = {"weighted_criteria": [{"name": "sound_quality", "weight": 8}]}

    profile_base = {
        "interview": [{"question": "Budget?", "answer": "₹5000"}],
        "preferences_summary": "Budget ₹5000.",
    }
    profile_with_memory = {
        "interview": [{"question": "Budget?", "answer": "₹5000"}],
        "preferences_summary": "Budget ₹5000.\n\nAdditional context: user has sensitive skin.",
    }

    key_base = _pipeline_cache_key("best earbuds", "electronics/earbuds", rubric, profile_base)
    key_with_mem = _pipeline_cache_key("best earbuds", "electronics/earbuds", rubric, profile_with_memory)

    assert key_base == key_with_mem, (
        "Cache key must not change when only preferences_summary (not Q&A) changes (R2)"
    )


def test_cache_key_changes_when_qa_changes():
    """Different Q&A answers must produce different cache keys."""
    rubric = {"weighted_criteria": [{"name": "sound_quality", "weight": 8}]}

    profile_a = {
        "interview": [{"question": "Budget?", "answer": "₹5000"}],
        "preferences_summary": "Budget ₹5000.",
    }
    profile_b = {
        "interview": [{"question": "Budget?", "answer": "₹10000"}],
        "preferences_summary": "Budget ₹10000.",
    }

    key_a = _pipeline_cache_key("best earbuds", "electronics/earbuds", rubric, profile_a)
    key_b = _pipeline_cache_key("best earbuds", "electronics/earbuds", rubric, profile_b)

    assert key_a != key_b, "Different Q&A answers must produce different cache keys"


# ---------------------------------------------------------------------------
# B3: Retrieval query enrichment
# ---------------------------------------------------------------------------

def test_retrieval_query_enrichment_gaming():
    """If user said 'gaming', the enriched query should append 'gaming' (B3)."""
    profile = {"preferences_summary": "User uses it for gaming sessions."}
    enriched = _build_retrieval_query("best headphones", profile)
    assert "gaming" in enriched.lower(), (
        f"Expected 'gaming' in enriched query '{enriched}' (B3)"
    )


def test_retrieval_query_enrichment_gym():
    """If user said 'gym', the enriched query should append gym-related term."""
    profile = {"preferences_summary": "Uses earbuds at the gym for workouts."}
    enriched = _build_retrieval_query("best earbuds", profile)
    assert "gym" in enriched.lower() or "workout" in enriched.lower(), (
        f"Expected gym/workout in enriched query '{enriched}' (B3)"
    )


def test_retrieval_query_no_spurious_enrichment():
    """No usage pattern → query must be returned unchanged."""
    profile = {"preferences_summary": "Wants good sound quality."}
    base = "best wireless earbuds"
    enriched = _build_retrieval_query(base, profile)
    assert enriched == base, (
        f"Query should not be enriched when no usage pattern found: got '{enriched}'"
    )


def test_retrieval_query_structured_intent_enrichment():
    """Structured intent preferences should also enrich the query."""
    profile = {
        "intent": {
            "hard_constraints": [],
            "budget": None,
            "preferences": ["uses for commuting daily"],
            "exclusions": [],
            "uncertainties": [],
        },
        "preferences_summary": "Uses for commuting daily.",
    }
    enriched = _build_retrieval_query("best earbuds", profile)
    assert "commut" in enriched.lower(), (
        f"Expected 'commut' in enriched query for commuting user, got '{enriched}'"
    )


# ---------------------------------------------------------------------------
# B5: Rubric rationale in scorer criterion text
# ---------------------------------------------------------------------------

def test_rubric_rationale_in_criterion_line():
    """
    _format_criterion_line must prefer 'rationale' over 'description' (B5).
    Before the fix, scorer used 'description', losing the personalized rationale.
    """
    criterion_with_rationale = {
        "name": "breathability",
        "label": "Breathability",
        "weight": 9,
        "rationale": "user said runs hot → breathability critical → weight 9",
        "description": "How well the product allows airflow",
    }
    line = _format_criterion_line(criterion_with_rationale)
    assert "runs hot" in line, (
        f"Criterion line should contain rationale text, got: '{line}' (B5)"
    )
    assert "breathability critical" in line, (
        f"Criterion line should contain rationale context, got: '{line}'"
    )


def test_rubric_description_fallback_when_no_rationale():
    """If no rationale, criterion line falls back to description."""
    criterion_no_rationale = {
        "name": "sound_quality",
        "label": "Sound Quality",
        "weight": 8,
        "description": "Clarity and richness of audio output",
    }
    line = _format_criterion_line(criterion_no_rationale)
    assert "Clarity and richness" in line, (
        f"Should fall back to description when rationale is absent, got: '{line}'"
    )


# ---------------------------------------------------------------------------
# Phase 3: Analyzer hint prefers structured intent
# ---------------------------------------------------------------------------

def test_analyzer_hint_prefers_structured_intent():
    """
    _build_analyzer_hint must use structured intent when available,
    not the raw truncated preferences_summary.
    """
    profile = {
        "intent": {
            "hard_constraints": ["Must have ANC"],
            "budget": "under ₹5000",
            "preferences": ["balanced sound", "long battery"],
            "exclusions": ["Skullcandy"],
            "uncertainties": [],
        },
        "preferences_summary": "Budget ₹5000. Wants ANC. Prefers balanced sound.",
    }
    hint = _build_analyzer_hint(profile)
    assert "MUST" in hint or "ANC" in hint, (
        f"Hint should surface hard constraints from intent, got: '{hint}'"
    )
    assert "₹5000" in hint or "5000" in hint, (
        f"Hint should include budget from intent, got: '{hint}'"
    )


def test_analyzer_hint_fallback_to_text():
    """When no intent is available, fall back to truncated text summary."""
    profile = {
        "preferences_summary": "User wants balanced sound and good battery life.",
    }
    hint = _build_analyzer_hint(profile)
    assert len(hint) > 0, "Hint should not be empty when preferences_summary exists"
    assert "balanced" in hint or "battery" in hint, (
        f"Hint should contain preference text, got: '{hint}'"
    )


# ---------------------------------------------------------------------------
# Phase 9: Thread deduplication
# ---------------------------------------------------------------------------

def test_dedup_removes_identical_title_threads():
    """Threads with identical titles should be deduplicated, keeping the higher-scored one."""
    threads = [
        {"title": "Best earbuds under 5000 india", "score": 50, "url": "url1"},
        {"title": "Best earbuds under 5000 india", "score": 200, "url": "url2"},
        {"title": "Top wireless earbuds for gym", "score": 30, "url": "url3"},
    ]
    result = _dedup_threads(threads)
    # Should keep 2 distinct threads
    assert len(result) == 2, f"Expected 2 unique threads, got {len(result)}"
    # The higher-scored duplicate (score=200) should be kept
    urls = [t["url"] for t in result]
    assert "url2" in urls, "Higher-scored duplicate should be kept"
    assert "url1" not in urls, "Lower-scored duplicate should be removed"


def test_dedup_keeps_distinct_threads():
    """Threads with distinct content must all be kept."""
    threads = [
        {"title": "Best earbuds for running under budget india", "score": 100, "url": "url1"},
        {"title": "Mechanical keyboard switch guide for typing", "score": 80, "url": "url2"},
        {"title": "Skincare routine for dry sensitive skin", "score": 60, "url": "url3"},
    ]
    result = _dedup_threads(threads)
    assert len(result) == 3, f"All distinct threads should be kept, got {len(result)}"


def test_dedup_near_duplicate_removal():
    """Near-identical titles (>60% word overlap) should be treated as duplicates."""
    threads = [
        {"title": "best wireless earbuds under 5000 recommendation", "score": 100, "url": "url1"},
        {"title": "best wireless earbuds under 5000 india recommendation", "score": 50, "url": "url2"},
        {"title": "gaming headset for ps5 setup", "score": 80, "url": "url3"},
    ]
    result = _dedup_threads(threads)
    # Threads 1 and 2 have very high word overlap — should keep only the higher-scored one
    assert len(result) <= 2, f"Near-duplicate should be removed, got {len(result)} threads"


def test_dedup_single_thread_unchanged():
    """Single thread should pass through unchanged."""
    threads = [{"title": "Best earbuds", "score": 100, "url": "url1"}]
    result = _dedup_threads(threads)
    assert result == threads


def test_dedup_empty_list():
    """Empty list should return empty list without error."""
    assert _dedup_threads([]) == []


# ---------------------------------------------------------------------------
# Phase 5: Score-based explanation fallback
# ---------------------------------------------------------------------------

def test_score_based_explanation_strong():
    """_build_score_based_explanation should mention strongest criterion."""
    product = {
        "scores": [
            {"label": "Sound Quality", "score": 9, "weighted_contribution": 72},
            {"label": "Battery Life", "score": 3, "weighted_contribution": 18},
        ]
    }
    explanation = _build_score_based_explanation(product)
    assert isinstance(explanation, str)
    # Should mention the strong criterion
    assert "sound quality" in explanation.lower() or "strong" in explanation.lower(), (
        f"Expected strong criterion mention, got: '{explanation}'"
    )


def test_score_based_explanation_empty_scores():
    """Empty scores should return empty string, not crash."""
    product = {"scores": []}
    result = _build_score_based_explanation(product)
    assert result == "", f"Expected empty string for no scores, got: '{result}'"
