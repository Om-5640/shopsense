"""
End-to-end API smoke tests using FastAPI TestClient.

Tests every endpoint for correct HTTP status, response shape, and error handling.

No real LLM calls — agents.run_agent is patched at the module level via the
`no_llm_calls` autouse fixture.  Any endpoint that reaches the LLM layer
returns a safe mock response instead of hitting a real API.

No real DB — uses an in-memory SQLite instance via the isolated_db fixture.

Patch-path note: functions imported with `from X import Y` into main.py
create LOCAL references in main.  Patching `X.Y` misses those references;
patches must target `main.Y` for those symbols.
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))

os.environ.setdefault("GEMINI_API_KEY",    "dummy")
os.environ.setdefault("GROQ_API_KEY",      "dummy")
os.environ.setdefault("SERPER_API_KEY",    "dummy")
os.environ.setdefault("OPENROUTER_API_KEY","dummy")

import pytest


# ---------------------------------------------------------------------------
# Safe mock responses per agent type
# ---------------------------------------------------------------------------

_AGENT_RESPONSES: dict[str, str] = {
    "criteria_generator": json.dumps([
        {"name": "battery_life", "label": "Battery Life", "description": ""},
        {"name": "sound_quality", "label": "Sound Quality", "description": ""},
    ]),
    "rubric_generator": json.dumps({"weighted_criteria": [
        {"name": "battery_life", "label": "Battery Life", "weight": 7, "rationale": "mocked"},
    ]}),
    "gap_filler": json.dumps({"inferred_weights": []}),
    "preference_summarizer": "Mocked user preference summary.",
    "interview_questioner": json.dumps({
        "question": "What is your budget?",
        "why_asking": "to filter",
        "targets_criterion": "price_to_value",
        "is_done": True,
    }),
    "main_analyzer": json.dumps({
        "summary": "Mocked analysis summary.",
        "products": [{"name": "Mock Product", "mention_count": 1, "signal_strength": "low"}],
        "materials": [],
    }),
    "product_scorer": json.dumps({"products": []}),
    "signal_extractor": json.dumps({"signals": []}),
    "explanation_writer": "This product is recommended because it meets your needs.",
    "cross_validator": json.dumps({"products": []}),
}


def _mock_run_agent(agent_name: str, user_prompt: str = "", system: str = "") -> str:
    """Return a safe canned response for every agent type. Never makes HTTP calls."""
    return _AGENT_RESPONSES.get(agent_name, "{}")


# ---------------------------------------------------------------------------
# Module-level LLM firewall — fires before EVERY test in this module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def no_llm_calls():
    """
    Patch agents.run_agent globally for the entire e2e test session.
    This is the definitive firewall: every code path that eventually calls
    run_agent (criteria, rubric, interview, memory context, etc.) returns a
    safe mock instead of hitting a real API.  No individual-test patches
    needed for LLM-touching endpoints.
    """
    with patch("agents.run_agent", side_effect=_mock_run_agent):
        yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Shared TestClient for all e2e tests. Uses an isolated SQLite DB."""
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    import db as _db
    import threading as _th
    _db._SQLITE_PATH = db_path
    _db.POSTGRES_URL = ""
    _db._local = _th.local()
    _db._pg_pool = None
    _db.init_db()

    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# Import after env vars are set
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert "status" in r.json()


class TestDetect:
    def test_detect_returns_category(self, client):
        # detect_category is `from category import detect_category` in main.py
        # → patch main.detect_category
        mock_result = {"category": "electronics/earbuds", "primary_noun": "earbuds", "region": "global",
                       "needs_disambiguation": False, "needs_region_clarification": False, "options": []}
        with patch("main.detect_category", return_value=mock_result):
            r = client.post("/api/detect", json={"query": "best earbuds under 3000"})
        assert r.status_code == 200
        assert "category" in r.json()

    def test_detect_empty_query_still_responds(self, client):
        mock_result = {"category": "general", "primary_noun": "", "region": "global",
                       "needs_disambiguation": False, "needs_region_clarification": False, "options": []}
        with patch("main.detect_category", return_value=mock_result):
            r = client.post("/api/detect", json={"query": ""})
        assert r.status_code == 200


class TestCriteria:
    def test_criteria_returns_list(self, client):
        # generate_criteria is `from criteria import generate_criteria` in main.py
        # → patch main.generate_criteria (NOT criteria.generate_criteria)
        mock_criteria = [{"name": "battery_life", "label": "Battery Life", "description": ""}]
        with patch("main.generate_criteria", return_value=mock_criteria):
            r = client.post("/api/criteria", json={"category": "electronics/earbuds"})
        assert r.status_code == 200
        data = r.json()
        assert "criteria" in data
        assert isinstance(data["criteria"], list)


class TestProfile:
    def test_get_profile_missing_returns_404(self, client):
        r = client.get("/api/profile/electronics/headphones-e2e-nomatch")
        assert r.status_code == 404

    def test_save_and_get_profile(self, client):
        profile = {"preferences_summary": "needs ANC e2e", "interview": []}
        r = client.post("/api/profile/electronics/earbuds-e2e", json={"profile": profile})
        assert r.status_code == 200
        r2 = client.get("/api/profile/electronics/earbuds-e2e")
        assert r2.status_code == 200
        assert r2.json().get("preferences_summary") == "needs ANC e2e"


class TestSearch:
    def _start_search(self, client):
        payload = {
            "query": "best earbuds e2e",
            "category": "electronics/earbuds",
            "region": "global",
            "profile": {},
            "rubric": {"weighted_criteria": [{"name": "battery_life", "label": "Battery", "weight": 5}]},
        }
        with patch("pipeline_runner.start_pipeline"):
            r = client.post("/api/search", json=payload)
        return r

    def test_start_search_returns_search_id(self, client):
        r = self._start_search(client)
        assert r.status_code == 200
        assert "search_id" in r.json()

    def test_get_search_result_after_create(self, client):
        r = self._start_search(client)
        search_id = r.json()["search_id"]
        assert client.get(f"/api/search/{search_id}").status_code == 200

    def test_cancel_search(self, client):
        r = self._start_search(client)
        search_id = r.json()["search_id"]
        assert client.post(f"/api/search/{search_id}/cancel").status_code == 200

    def test_get_nonexistent_search_404(self, client):
        assert client.get("/api/search/does-not-exist-99999").status_code == 404

    def test_diagnostics_for_existing_search(self, client):
        r = self._start_search(client)
        search_id = r.json()["search_id"]
        r2 = client.get(f"/api/search/{search_id}/diagnostics")
        assert r2.status_code == 200
        data = r2.json()
        assert "search_id" in data and "status" in data

    def test_diagnostics_for_nonexistent_search_404(self, client):
        assert client.get("/api/search/ghost-id/diagnostics").status_code == 404


class TestSearchesList:
    def test_list_searches_returns_array(self, client):
        r = client.get("/api/searches")
        assert r.status_code == 200
        data = r.json()
        searches = data.get("searches", data) if isinstance(data, dict) else data
        assert isinstance(searches, list)


class TestMemory:
    def test_memory_context_returns_structure(self, client):
        r = client.get("/api/memory/context")
        assert r.status_code == 200
        assert "has_memory" in r.json()

    def test_memory_signals_returns_list(self, client):
        r = client.get("/api/memory/signals")
        assert r.status_code == 200
        data = r.json()
        signals = data.get("signals", data) if isinstance(data, dict) else data
        assert isinstance(signals, list)

    def test_memory_products_returns_list(self, client):
        r = client.get("/api/memory/products")
        assert r.status_code == 200
        data = r.json()
        products = data.get("products", data) if isinstance(data, dict) else data
        assert isinstance(products, list)

    def test_mark_product_bought(self, client):
        r = client.post("/api/memory/bought", json={
            "product_name": "Test Widget",
            "category": "electronics/earbuds",
        })
        assert r.status_code == 200

    def test_clear_all_memory(self, client):
        assert client.delete("/api/memory/all").status_code == 200


class TestProviders:
    def test_providers_status_returns_dict(self, client):
        r = client.get("/api/providers/status")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        for name in ("groq", "gemini"):
            if name in data["providers"]:
                assert "configured" in data["providers"][name]
                assert "session_alive" in data["providers"][name]


class TestRubric:
    def test_rubric_endpoint_returns_weighted_criteria(self, client):
        # generate_rubric is `from rubric import generate_rubric` in main.py
        # → patch main.generate_rubric (NOT rubric.generate_rubric)
        # summarize_user_profile is covered by the no_llm_calls fixture
        mock_rubric = {"weighted_criteria": [
            {"name": "battery_life", "label": "Battery Life", "weight": 8, "rationale": "mocked"},
        ]}
        with patch("main.generate_rubric", return_value=mock_rubric):
            r = client.post("/api/rubric", json={
                "category": "electronics/earbuds",
                "criteria": [{"name": "battery_life", "label": "Battery Life", "description": ""}],
                "profile": {},
            })
        assert r.status_code == 200
        data = r.json()
        rubric_data = data.get("rubric", data)
        assert "weighted_criteria" in rubric_data
