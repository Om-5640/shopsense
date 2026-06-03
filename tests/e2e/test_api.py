"""
End-to-end API smoke tests using FastAPI TestClient.

Tests every endpoint for correct HTTP status, response shape, and error handling.
No real LLM calls — all provider calls are mocked.
No real DB — uses an in-memory SQLite instance via the isolated_db fixture.
"""

from __future__ import annotations

import json
import sys
import threading
import os
from pathlib import Path

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
from fastapi.testclient import TestClient


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


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data


# ── Category detection ────────────────────────────────────────────────────────

class TestDetect:
    def test_detect_returns_category(self, client):
        from unittest.mock import patch
        mock_result = {"category": "electronics/earbuds", "primary_noun": "earbuds", "region": "global"}
        with patch("category.detect_category", return_value=mock_result):
            r = client.post("/api/detect", json={"query": "best earbuds under 3000"})
        assert r.status_code == 200
        assert "category" in r.json()

    def test_detect_empty_query_still_responds(self, client):
        from unittest.mock import patch
        mock_result = {"category": "general", "primary_noun": "", "region": "global"}
        with patch("category.detect_category", return_value=mock_result):
            r = client.post("/api/detect", json={"query": ""})
        assert r.status_code == 200


# ── Criteria ──────────────────────────────────────────────────────────────────

class TestCriteria:
    def test_criteria_returns_list(self, client):
        from unittest.mock import patch
        mock_criteria = [
            {"name": "battery_life", "label": "Battery Life", "description": "..."},
        ]
        with patch("criteria.generate_criteria", return_value=mock_criteria):
            r = client.post("/api/criteria", json={"category": "electronics/earbuds"})
        assert r.status_code == 200
        data = r.json()
        assert "criteria" in data
        assert isinstance(data["criteria"], list)


# ── Profile ───────────────────────────────────────────────────────────────────

class TestProfile:
    def test_get_profile_missing_returns_404(self, client):
        r = client.get("/api/profile/electronics/headphones-e2e-test")
        assert r.status_code == 404

    def test_save_and_get_profile(self, client):
        profile = {"preferences_summary": "needs ANC e2e", "interview": []}
        r = client.post("/api/profile/electronics/earbuds-e2e", json={"profile": profile})
        assert r.status_code == 200
        r2 = client.get("/api/profile/electronics/earbuds-e2e")
        assert r2.status_code == 200
        data = r2.json()
        assert data.get("preferences_summary") == "needs ANC e2e"


# ── Search lifecycle ──────────────────────────────────────────────────────────

class TestSearch:
    def _start_search(self, client):
        """Fire a search start and return the response dict."""
        from unittest.mock import patch, MagicMock
        payload = {
            "query": "best earbuds e2e",
            "category": "electronics/earbuds",
            "region": "global",
            "profile": {},
            "rubric": {"weighted_criteria": [{"name": "battery_life", "label": "Battery", "weight": 5}]},
        }
        # Mock start_pipeline so no real thread is launched
        with patch("pipeline_runner.start_pipeline"):
            r = client.post("/api/search", json=payload)
        return r

    def test_start_search_returns_search_id(self, client):
        r = self._start_search(client)
        assert r.status_code == 200
        data = r.json()
        assert "search_id" in data

    def test_get_search_result_after_create(self, client):
        r = self._start_search(client)
        search_id = r.json()["search_id"]
        r2 = client.get(f"/api/search/{search_id}")
        assert r2.status_code == 200

    def test_cancel_search(self, client):
        r = self._start_search(client)
        search_id = r.json()["search_id"]
        r2 = client.post(f"/api/search/{search_id}/cancel")
        assert r2.status_code == 200

    def test_get_nonexistent_search_404(self, client):
        r = client.get("/api/search/does-not-exist-12345")
        assert r.status_code == 404

    def test_diagnostics_for_existing_search(self, client):
        r = self._start_search(client)
        search_id = r.json()["search_id"]
        r2 = client.get(f"/api/search/{search_id}/diagnostics")
        assert r2.status_code == 200
        data = r2.json()
        assert "search_id" in data
        assert "status" in data

    def test_diagnostics_for_nonexistent_search_404(self, client):
        r = client.get("/api/search/ghost-id/diagnostics")
        assert r.status_code == 404


# ── Searches list ─────────────────────────────────────────────────────────────

class TestSearchesList:
    def test_list_searches_returns_array(self, client):
        r = client.get("/api/searches")
        assert r.status_code == 200
        data = r.json()
        # endpoint returns {"searches": [...]} or a bare list — both are valid shapes
        searches = data.get("searches", data) if isinstance(data, dict) else data
        assert isinstance(searches, list)


# ── Memory ────────────────────────────────────────────────────────────────────

class TestMemory:
    def test_memory_context_returns_structure(self, client):
        r = client.get("/api/memory/context")
        assert r.status_code == 200
        data = r.json()
        assert "has_memory" in data

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
        r = client.delete("/api/memory/all")
        assert r.status_code == 200


# ── Providers status ──────────────────────────────────────────────────────────

class TestProviders:
    def test_providers_status_returns_dict(self, client):
        r = client.get("/api/providers/status")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        providers = data["providers"]
        for name in ("groq", "gemini"):
            if name in providers:
                assert "configured" in providers[name]
                assert "session_alive" in providers[name]


# ── Rubric ────────────────────────────────────────────────────────────────────

class TestRubric:
    def test_rubric_endpoint_returns_weighted_criteria(self, client):
        from unittest.mock import patch
        mock_rubric = {
            "weighted_criteria": [
                {"name": "battery_life", "label": "Battery Life", "weight": 8, "rationale": "user needs it"},
            ]
        }
        with patch("rubric.generate_rubric", return_value=mock_rubric):
            r = client.post("/api/rubric", json={
                "category": "electronics/earbuds",
                "criteria": [{"name": "battery_life", "label": "Battery Life", "description": ""}],
                "profile": {},
            })
        assert r.status_code == 200
        data = r.json()
        # endpoint returns rubric directly or wrapped — accept both shapes
        rubric_data = data.get("rubric", data)
        assert "weighted_criteria" in rubric_data
