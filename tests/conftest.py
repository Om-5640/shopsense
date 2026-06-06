"""
Root test configuration and shared fixtures.

Provides:
  - sys.path setup so all tests can import project modules without per-file boilerplate
  - isolated_db: fresh SQLite DB per test (opt-in, not autouse — request explicitly)
  - mock_db_cache: patches embedding DB cache helpers to no-ops (opt-in)
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_API_DIR = _ROOT / "api"

for _p in [str(_ROOT), str(_API_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# DB isolation (opt-in — use as a fixture parameter, not autouse)
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """
    Each test gets its own fresh SQLite DB at a temp path.
    Use as a fixture argument in tests that touch DB state.

    Usage:
        def test_something(isolated_db):
            from db import create_search, get_search
            create_search("s1", "laptop")
            assert get_search("s1") is not None
    """
    db_path = tmp_path / "test.db"
    import db as _db

    monkeypatch.setattr(_db, "_SQLITE_PATH", db_path)
    monkeypatch.setattr(_db, "POSTGRES_URL", "")
    # Reset thread-local connection so it opens against the new path
    _db._local = threading.local()
    _db._pg_pool = None
    _db.init_db()
    yield db_path
    _db.close_db_connection()


# ---------------------------------------------------------------------------
# Embedding DB cache mock (opt-in — prevents unit tests from touching real DB)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_db_cache(monkeypatch):
    """
    Replaces DB-tier embedding cache with a simple in-memory dict.
    Useful in unit tests for embeddings.py to avoid DB I/O.

    Returns the in-memory dict so tests can inspect it.
    """
    store: dict[str, list] = {}

    def _fake_get(hash_key: str):
        return store.get(hash_key)

    def _fake_set(hash_key: str, text: str, provider: str, vec: list):
        store[hash_key] = vec

    import embeddings as _emb
    monkeypatch.setattr(_emb, "_HAS_DB_CACHE", True)
    monkeypatch.setattr(_emb, "_db_get_embedding", _fake_get)
    monkeypatch.setattr(_emb, "_db_set_embedding", _fake_set)

    return store
