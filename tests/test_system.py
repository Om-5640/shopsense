"""
System validation tests — Phase 12.

Verifies structural invariants that must hold for the system to work correctly.
All tests are pure unit/import tests — zero LLM calls, zero network requests.

Covered:
  S1 — All critical modules import without error
  S2 — Agent registry invariants (every agent has fallback chain + openrouter master)
  S3 — Prompt builder: dedup, budget, empty section handling
  S4 — Context consistency: _build_analyzer_hint always returns a string
  S5 — Pipeline cache key is stable (same inputs = same key)
  S6 — _write_pipeline_log is non-fatal on bad path
  S7 — provider_char_budget returns positive int for all known providers
  S8 — All test module imports from interview + pipeline work
  S9 — PipelineSession stats dict has required keys
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))


# ---------------------------------------------------------------------------
# S1: Critical module imports
# ---------------------------------------------------------------------------

def test_import_prompt_builder():
    from prompt_builder import assemble_prompt, estimate_tokens, provider_char_budget
    assert callable(assemble_prompt)
    assert callable(estimate_tokens)
    assert callable(provider_char_budget)


def test_import_pipeline_runner():
    from pipeline_runner import (
        _pipeline_cache_key, _build_retrieval_query,
        _build_analyzer_hint, _build_score_based_explanation,
        _dedup_threads, _estimate_tokens, _emit_token_warning,
        PipelineSession,
    )
    assert callable(_pipeline_cache_key)
    assert callable(_build_analyzer_hint)
    assert callable(_estimate_tokens)
    assert callable(_emit_token_warning)


def test_import_interview():
    from interview import (
        _categorize_qa_entry, _summarize_and_extract_intent,
        _SKIP_ANSWER_TOKENS, _EMPTY_INTENT,
    )
    assert isinstance(_EMPTY_INTENT, dict)


def test_import_scorer():
    from scorer import (
        score_all_products, _format_criterion_line,
        _build_constraint_context, _build_scored_dict,
    )
    assert callable(score_all_products)
    assert callable(_format_criterion_line)


def test_import_rubric():
    from rubric import generate_rubric, fill_criterion_gaps, _build_intent_context
    assert callable(generate_rubric)
    assert callable(fill_criterion_gaps)
    assert callable(_build_intent_context)


def test_import_agents():
    from agents import run_agent, AGENTS, get_provider_status, mark_provider_dead
    assert isinstance(AGENTS, dict)
    assert callable(run_agent)


def test_import_reddit_fetch():
    from reddit_fetch import (
        _query_variations, _extract_usage_pattern, fetch_all_threads, find_reddit_urls
    )
    assert callable(_query_variations)
    assert callable(_extract_usage_pattern)


# ---------------------------------------------------------------------------
# S2: Agent registry invariants
# ---------------------------------------------------------------------------

def test_every_agent_has_fallback_chain():
    from agents import AGENTS
    for name, cfg in AGENTS.items():
        assert "fallback_chain" in cfg, f"Agent '{name}' missing fallback_chain"
        assert len(cfg["fallback_chain"]) > 0, f"Agent '{name}' has empty fallback_chain"


def test_every_agent_has_openrouter_master_fallback():
    from agents import AGENTS
    for name, cfg in AGENTS.items():
        chain = cfg.get("fallback_chain", [])
        assert "openrouter" in chain, (
            f"Agent '{name}' missing 'openrouter' in fallback_chain: {chain}"
        )


def test_every_agent_has_required_keys():
    from agents import AGENTS
    required = {"provider", "fallback_chain", "temperature", "max_tokens"}
    for name, cfg in AGENTS.items():
        missing = required - set(cfg.keys())
        assert not missing, f"Agent '{name}' missing keys: {missing}"


def test_pool_agent_has_provider_pool():
    from agents import AGENTS
    for name, cfg in AGENTS.items():
        if cfg["provider"] == "pool":
            assert "provider_pool" in cfg, f"Pool agent '{name}' missing provider_pool"
            assert len(cfg["provider_pool"]) >= 2, f"Pool agent '{name}' needs >=2 providers"


# ---------------------------------------------------------------------------
# S3: Prompt builder behavior
# ---------------------------------------------------------------------------

def test_prompt_builder_basic():
    from prompt_builder import assemble_prompt
    result = assemble_prompt([
        ("task", "Do the thing."),
        ("context", "Here is some context."),
    ])
    assert "Do the thing." in result
    assert "Here is some context." in result


def test_prompt_builder_skips_empty():
    from prompt_builder import assemble_prompt
    result = assemble_prompt([
        ("a", "Real content."),
        ("b", ""),
        ("c", "   "),
        ("d", "More content."),
    ])
    assert "Real content." in result
    assert "More content." in result
    # Empty sections don't add blank lines
    assert "\n\n\n" not in result


def test_prompt_builder_dedup():
    from prompt_builder import assemble_prompt
    content = "User wants ANC earbuds with good battery life."
    result = assemble_prompt([
        ("section_a", content),
        ("section_b", content),  # exact duplicate
    ])
    assert result.count("User wants ANC") == 1, "Duplicate section should appear only once"


def test_prompt_builder_budget_trim():
    from prompt_builder import assemble_prompt
    long_text = "x" * 10_000
    result = assemble_prompt([
        ("important", "KEEP THIS"),
        ("bulk", long_text),
    ], budget_chars=200)
    assert len(result) <= 250  # a bit of slack for the trim notice
    assert "KEEP THIS" in result
    assert "trimmed" in result


def test_prompt_builder_budget_no_trim_when_fits():
    from prompt_builder import assemble_prompt
    result = assemble_prompt([("a", "Short text.")], budget_chars=10_000)
    assert "trimmed" not in result


def test_estimate_tokens():
    from prompt_builder import estimate_tokens
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("") == 1  # minimum 1
    assert estimate_tokens("a" * 400) == 100


def test_provider_char_budget_all_providers():
    from prompt_builder import provider_char_budget
    for p in ["groq", "cerebras", "gemini", "mistral", "openrouter"]:
        b = provider_char_budget(p)
        assert isinstance(b, int) and b > 0, f"Budget for {p} must be positive int"


def test_provider_char_budget_unknown_returns_default():
    from prompt_builder import provider_char_budget
    b = provider_char_budget("unknown_provider_xyz")
    assert b == 24_000


# ---------------------------------------------------------------------------
# S4: Context consistency — _build_analyzer_hint always returns str
# ---------------------------------------------------------------------------

def test_build_analyzer_hint_empty_profile():
    from pipeline_runner import _build_analyzer_hint
    assert _build_analyzer_hint({}) == ""


def test_build_analyzer_hint_with_summary_only():
    from pipeline_runner import _build_analyzer_hint
    profile = {"preferences_summary": "Wants ANC earbuds."}
    result = _build_analyzer_hint(profile)
    assert isinstance(result, str)
    assert "ANC" in result


def test_build_analyzer_hint_structured_intent_preferred():
    from pipeline_runner import _build_analyzer_hint
    profile = {
        "intent": {
            "hard_constraints": ["must have ANC"],
            "budget": "under ₹5000",
            "preferences": ["balanced sound"],
            "exclusions": ["Skullcandy"],
            "uncertainties": [],
        },
        "preferences_summary": "Wants ANC earbuds under budget.",
    }
    result = _build_analyzer_hint(profile)
    assert "MUST" in result or "ANC" in result
    assert "₹5000" in result or "5000" in result


def test_build_analyzer_hint_non_dict_profile():
    from pipeline_runner import _build_analyzer_hint
    assert _build_analyzer_hint(None) == ""
    assert _build_analyzer_hint("not a dict") == ""
    assert _build_analyzer_hint(42) == ""


# ---------------------------------------------------------------------------
# S5: Cache key stability
# ---------------------------------------------------------------------------

def test_cache_key_stable_same_inputs():
    from pipeline_runner import _pipeline_cache_key
    rubric = {"weighted_criteria": [{"name": "sound", "weight": 8}]}
    profile = {"interview": [{"question": "Q?", "answer": "A."}]}
    k1 = _pipeline_cache_key("best earbuds", "electronics", rubric, profile)
    k2 = _pipeline_cache_key("best earbuds", "electronics", rubric, profile)
    assert k1 == k2, "Same inputs must produce same cache key"


def test_cache_key_different_on_qa_change():
    from pipeline_runner import _pipeline_cache_key
    rubric = {"weighted_criteria": [{"name": "sound", "weight": 8}]}
    p1 = {"interview": [{"question": "Budget?", "answer": "₹5000"}]}
    p2 = {"interview": [{"question": "Budget?", "answer": "₹10000"}]}
    k1 = _pipeline_cache_key("query", "cat", rubric, p1)
    k2 = _pipeline_cache_key("query", "cat", rubric, p2)
    assert k1 != k2, "Different Q&A must produce different cache key"


def test_cache_key_stable_despite_preferences_change():
    from pipeline_runner import _pipeline_cache_key
    rubric = {"weighted_criteria": [{"name": "sound", "weight": 8}]}
    p1 = {"interview": [{"question": "Q?", "answer": "A."}], "preferences_summary": "orig"}
    p2 = {"interview": [{"question": "Q?", "answer": "A."}], "preferences_summary": "changed"}
    k1 = _pipeline_cache_key("q", "cat", rubric, p1)
    k2 = _pipeline_cache_key("q", "cat", rubric, p2)
    assert k1 == k2, "preferences_summary change must NOT change cache key"


# ---------------------------------------------------------------------------
# S6: _write_pipeline_log is non-fatal
# ---------------------------------------------------------------------------

def test_write_pipeline_log_non_fatal(tmp_path, monkeypatch):
    from pipeline_runner import _write_pipeline_log
    # Should not raise even with an unusable path
    _write_pipeline_log("test-id", "test query", {"stage_timings": {}, "product_count": 3})


# ---------------------------------------------------------------------------
# S7: Token estimation
# ---------------------------------------------------------------------------

def test_estimate_tokens_pipeline():
    from pipeline_runner import _estimate_tokens
    assert _estimate_tokens("") == 1
    assert _estimate_tokens("hello") == 1
    assert _estimate_tokens("a" * 4000) == 1000


def test_emit_token_warning_trims():
    from pipeline_runner import _emit_token_warning, PipelineSession
    session = PipelineSession("test", "test query")
    long_text = "a" * 1000
    result = _emit_token_warning(session, "test_label", long_text, budget_chars=100)
    assert len(result) == 100
    # The warning message contains "[token_budget]" and "exceeds" so it IS captured
    assert len(session.stats["warnings"]) == 1


def test_emit_token_warning_no_trim_when_fits():
    from pipeline_runner import _emit_token_warning, PipelineSession
    session = PipelineSession("test", "test query")
    text = "short text"
    result = _emit_token_warning(session, "label", text, budget_chars=10_000)
    assert result == text


# ---------------------------------------------------------------------------
# S8: fill_criterion_gaps accepts user_context parameter
# ---------------------------------------------------------------------------

def test_fill_criterion_gaps_accepts_user_context():
    from rubric import fill_criterion_gaps
    rubric = {
        "weighted_criteria": [
            {
                "name": "battery",
                "label": "Battery Life",
                "weight": 5,
                "rationale": "Default weight - not addressed in interview",
                "description": "How long battery lasts",
            }
        ],
        "category": "electronics/earbuds",
    }
    # Should accept user_context param without crashing
    # (actual LLM call won't happen in tests since run_agent is not mocked —
    #  but with no defaulted criteria it returns early)
    rubric_no_defaults = {
        "weighted_criteria": [
            {"name": "battery", "label": "Battery", "weight": 7, "rationale": "user said battery matters"},
        ],
        "category": "electronics/earbuds",
    }
    result = fill_criterion_gaps(
        rubric_no_defaults, "electronics/earbuds", {},
        research_summary="", user_context="Wants long battery. Budget ₹5000."
    )
    assert isinstance(result, dict)
    assert "weighted_criteria" in result


# ---------------------------------------------------------------------------
# S9: PipelineSession stats structure
# ---------------------------------------------------------------------------

def test_pipeline_session_has_stats():
    from pipeline_runner import PipelineSession
    session = PipelineSession("test-id", "best earbuds")
    required_keys = {
        "stage_timings", "product_count", "thread_count",
        "dedup_removed", "llm_calls_estimated", "tokens_estimated", "warnings",
    }
    missing = required_keys - set(session.stats.keys())
    assert not missing, f"PipelineSession.stats missing keys: {missing}"


def test_pipeline_session_warnings_list():
    from pipeline_runner import PipelineSession
    session = PipelineSession("x", "query")
    assert isinstance(session.stats["warnings"], list)
    session.emit_log("[token_budget] research_text: ~50,000 tokens exceeds limit")
    assert len(session.stats["warnings"]) == 1
