"""
Integration tests for api/pipeline_runner.py.

Covers:
 - PipelineSession: create, emit, event_log cap
 - create_session / get_session / cancel_session
 - find_inflight_session: dedup by query
 - cleanup_old_sessions: evicts done/error/cancelled sessions, keeps running
 - _pipeline_cache_key: different rubric weights → different keys
 - _collect_provider_warnings: no-change = empty, dead provider = warning
 - pipeline_warnings field in session.stats
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))

import pytest
import os
os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("GROQ_API_KEY",   "dummy")
os.environ.setdefault("SERPER_API_KEY", "dummy")
os.environ.setdefault("OPENROUTER_API_KEY", "dummy")


@pytest.fixture(autouse=True)
def clear_sessions():
    """Reset session store and provider state between tests."""
    import pipeline_runner as _pr
    with _pr._sessions_lock:
        _pr._sessions.clear()
    import agents
    with agents._provider_state_lock:
        agents._dead_providers.clear()
    import llm_clients
    llm_clients._cb._blocked.clear()
    yield
    with _pr._sessions_lock:
        _pr._sessions.clear()


# ── PipelineSession ────────────────────────────────────────────────────────────

class TestPipelineSession:
    def test_initial_state(self):
        from pipeline_runner import PipelineSession
        s = PipelineSession("s-001", "best earbuds")
        assert s.status == "pending"
        assert s.query == "best earbuds"
        assert s.stats["pipeline_warnings"] == []
        assert s.stats["warnings"] == []

    def test_emit_puts_event_on_queue(self):
        from pipeline_runner import PipelineSession
        s = PipelineSession("s-002", "query")
        s.emit("stage_start", {"stage": "reddit_fetch"})
        item = s.events.get_nowait()
        assert item["type"] == "stage_start"
        assert item["data"]["stage"] == "reddit_fetch"

    def test_event_log_capped_at_max(self):
        from pipeline_runner import PipelineSession, _MAX_EVENT_LOG
        s = PipelineSession("s-003", "query")
        for i in range(_MAX_EVENT_LOG + 20):
            s.emit("log", {"message": f"msg {i}"})
        assert len(s._event_log) == _MAX_EVENT_LOG

    def test_heartbeat_not_added_to_event_log(self):
        from pipeline_runner import PipelineSession
        s = PipelineSession("s-004", "query")
        s.emit("heartbeat", {})
        assert len(s._event_log) == 0

    def test_emit_log_captures_token_budget_warning(self):
        from pipeline_runner import PipelineSession
        s = PipelineSession("s-005", "query")
        s.emit_log("[token_budget] summarize: ~5000 tokens exceeds limit ~4000. Trimming to fit.")
        assert len(s.stats["warnings"]) == 1

    def test_cancel_sets_cancelled_flag(self):
        from pipeline_runner import PipelineSession
        s = PipelineSession("s-006", "query")
        s.cancel()
        assert s._cancelled is True
        assert s.status == "cancelled"


# ── create_session / get_session ───────────────────────────────────────────────

class TestSessionLifecycle:
    def test_create_and_get_session(self):
        from pipeline_runner import create_session, get_session
        s = create_session("sess-001", "best earbuds")
        fetched = get_session("sess-001")
        assert fetched is s

    def test_get_nonexistent_returns_none(self):
        from pipeline_runner import get_session
        assert get_session("does-not-exist") is None

    def test_cancel_session(self):
        from pipeline_runner import create_session, cancel_session, get_session
        create_session("sess-002", "query")
        result = cancel_session("sess-002")
        assert result is True
        session = get_session("sess-002")
        assert session is not None
        assert session._cancelled is True

    def test_cancel_nonexistent_returns_false(self):
        from pipeline_runner import cancel_session
        assert cancel_session("ghost-session") is False


# ── find_inflight_session ──────────────────────────────────────────────────────

class TestFindInflightSession:
    def test_finds_running_session_by_query(self):
        from pipeline_runner import create_session, get_session, find_inflight_session
        s = create_session("inf-001", "best earbuds under 3000")
        s.status = "running"
        found = find_inflight_session("best earbuds under 3000")
        assert found is s

    def test_does_not_find_pending_session(self):
        from pipeline_runner import create_session, find_inflight_session
        create_session("inf-002", "pending query")  # status stays "pending"
        assert find_inflight_session("pending query") is None

    def test_does_not_find_done_session(self):
        from pipeline_runner import create_session, find_inflight_session
        s = create_session("inf-003", "done query")
        s.status = "done"
        assert find_inflight_session("done query") is None


# ── cleanup_old_sessions ───────────────────────────────────────────────────────

class TestCleanupOldSessions:
    def test_removes_done_sessions_older_than_threshold(self):
        from pipeline_runner import create_session, cleanup_old_sessions, get_session
        s = create_session("old-001", "old query")
        s.status = "done"
        s._created_at = time.time() - 7200  # 2 hours old
        cleanup_old_sessions()
        assert get_session("old-001") is None

    def test_keeps_running_sessions(self):
        from pipeline_runner import create_session, cleanup_old_sessions, get_session
        s = create_session("run-001", "active query")
        s.status = "running"
        s._created_at = time.time() - 7200  # old but running
        cleanup_old_sessions()
        assert get_session("run-001") is not None

    def test_removes_cancelled_sessions_older_than_cutoff(self):
        from pipeline_runner import create_session, cleanup_old_sessions, get_session
        s = create_session("canc-001", "cancelled query")
        s.status = "cancelled"
        s._created_at = time.time() - 7200
        cleanup_old_sessions()
        assert get_session("canc-001") is None

    def test_keeps_recent_done_sessions(self):
        from pipeline_runner import create_session, cleanup_old_sessions, get_session
        s = create_session("recent-001", "recent query")
        s.status = "done"
        s._created_at = time.time() - 60  # only 1 minute old
        cleanup_old_sessions()
        # Recent sessions should still be accessible
        assert get_session("recent-001") is not None


# ── _pipeline_cache_key ────────────────────────────────────────────────────────

class TestPipelineCacheKey:
    def test_different_rubric_weights_produce_different_keys(self):
        from pipeline_runner import _pipeline_cache_key
        rubric_a = {"weighted_criteria": [{"name": "battery", "weight": 8}]}
        rubric_b = {"weighted_criteria": [{"name": "battery", "weight": 3}]}
        key_a = _pipeline_cache_key("earbuds", "electronics", rubric_a, {})
        key_b = _pipeline_cache_key("earbuds", "electronics", rubric_b, {})
        assert key_a != key_b

    def test_different_queries_produce_different_keys(self):
        from pipeline_runner import _pipeline_cache_key
        rubric = {"weighted_criteria": [{"name": "battery", "weight": 5}]}
        key_a = _pipeline_cache_key("earbuds", "electronics", rubric, {})
        key_b = _pipeline_cache_key("headphones", "electronics", rubric, {})
        assert key_a != key_b

    def test_same_inputs_produce_same_key(self):
        from pipeline_runner import _pipeline_cache_key
        rubric = {"weighted_criteria": [{"name": "battery", "weight": 5}]}
        key_a = _pipeline_cache_key("earbuds", "electronics", rubric, {})
        key_b = _pipeline_cache_key("earbuds", "electronics", rubric, {})
        assert key_a == key_b

    def test_profile_qa_changes_key(self):
        from pipeline_runner import _pipeline_cache_key
        rubric = {"weighted_criteria": [{"name": "battery", "weight": 5}]}
        profile_a = {"interview": [{"question": "Budget?", "answer": "3000"}]}
        profile_b = {"interview": [{"question": "Budget?", "answer": "5000"}]}
        key_a = _pipeline_cache_key("earbuds", "electronics", rubric, profile_a)
        key_b = _pipeline_cache_key("earbuds", "electronics", rubric, profile_b)
        assert key_a != key_b


# ── _collect_provider_warnings ─────────────────────────────────────────────────

class TestCollectProviderWarnings:
    def test_no_change_produces_no_warnings(self):
        from pipeline_runner import _collect_provider_warnings
        from agents import get_provider_status
        initial = get_provider_status()
        warnings = _collect_provider_warnings(initial)
        assert warnings == []

    def test_dead_groq_produces_warning(self):
        import agents, time
        from pipeline_runner import _collect_provider_warnings
        # Snapshot before groq dies
        initial = {
            "groq":      {"configured": True, "session_alive": True, "circuit_blocked": False},
            "gemini":    {"configured": True, "session_alive": True, "circuit_blocked": False},
            "cerebras":  {"configured": False,"session_alive": True, "circuit_blocked": False},
            "mistral":   {"configured": False,"session_alive": True, "circuit_blocked": False},
            "openrouter":{"configured": False,"session_alive": True, "circuit_blocked": False},
        }
        with agents._provider_state_lock:
            agents._dead_providers["groq"] = time.time()
        try:
            warnings = _collect_provider_warnings(initial)
            assert any("Groq" in w or "groq" in w.lower() for w in warnings)
        finally:
            with agents._provider_state_lock:
                agents._dead_providers.pop("groq", None)

    def test_circuit_breaker_trip_produces_warning(self):
        import llm_clients, time
        from pipeline_runner import _collect_provider_warnings
        initial = {
            "groq":      {"configured": True, "session_alive": True, "circuit_blocked": False},
            "gemini":    {"configured": True, "session_alive": True, "circuit_blocked": False},
            "cerebras":  {"configured": False,"session_alive": True, "circuit_blocked": False},
            "mistral":   {"configured": False,"session_alive": True, "circuit_blocked": False},
            "openrouter":{"configured": False,"session_alive": True, "circuit_blocked": False},
        }
        llm_clients._cb._blocked["groq"] = (time.time() + 60, "circuit open: test")
        try:
            warnings = _collect_provider_warnings(initial)
            assert any("circuit" in w.lower() for w in warnings)
        finally:
            llm_clients._cb._blocked.pop("groq", None)

    def test_unconfigured_provider_ignored(self):
        from pipeline_runner import _collect_provider_warnings
        initial = {p: {"configured": False, "session_alive": True, "circuit_blocked": False}
                   for p in ["groq", "gemini", "mistral", "cerebras", "openrouter"]}
        warnings = _collect_provider_warnings(initial)
        assert warnings == []
