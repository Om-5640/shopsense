"""
Integration tests for api/db.py — SQLite path only (no Postgres required).

Covers:
 - init_db creates all tables
 - create_search / get_search / update_search / list_searches round-trip
 - save_profile_db / get_profile round-trip
 - save_signal / list_signals / delete_signal / clear_signals
 - save_signals_batch: bulk insert, dedup on conflict
 - save_product_memory / get_product_memory / delete round-trip
 - canonical name lookup (spaces/punctuation variants)
 - close_db_connection: closes and re-opens cleanly
 - _deserialize_search: corrupt JSON column → None (no crash)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))

import pytest


# ── Fixture: isolated SQLite DB per test ─────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets its own fresh SQLite database."""
    db_path = tmp_path / "test.db"
    import db as _db
    monkeypatch.setattr(_db, "_SQLITE_PATH", db_path)
    monkeypatch.setattr(_db, "POSTGRES_URL", "")
    # Reset thread-local connection so it opens against the new path
    import threading
    _db._local = threading.local()
    _db._pg_pool = None
    _db.init_db()
    yield
    # Clean up thread-local connection
    _db.close_db_connection()


# ── init_db ───────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_tables_exist_after_init(self):
        import db as _db
        conn = _db._sqlite_connect()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "Search" in tables
        assert "Profile" in tables
        assert "UserSignal" in tables
        assert "ProductMemory" in tables

    def test_init_db_idempotent(self):
        import db as _db
        _db.init_db()  # second call should not raise
        _db.init_db()


# ── Search CRUD ───────────────────────────────────────────────────────────────

class TestSearchCrud:
    def test_create_and_get(self):
        import db as _db
        _db.create_search("s001", "best earbuds", "electronics/earbuds", "india")
        row = _db.get_search("s001")
        assert row is not None
        assert row["query"] == "best earbuds"
        assert row["category"] == "electronics/earbuds"
        assert row["region"] == "india"

    def test_get_nonexistent_returns_none(self):
        import db as _db
        assert _db.get_search("does-not-exist") is None

    def test_update_search_status(self):
        import db as _db
        _db.create_search("s002", "query", "cat", "global")
        _db.update_search("s002", status="done")
        row = _db.get_search("s002")
        assert row["status"] == "done"

    def test_update_search_json_field(self):
        import db as _db
        _db.create_search("s003", "query", "cat", "global")
        analysis = {"summary": "Great results", "products": []}
        _db.update_search("s003", analysis=analysis)
        row = _db.get_search("s003")
        assert row["analysis"]["summary"] == "Great results"

    def test_list_searches_returns_all(self):
        import db as _db
        for i in range(3):
            _db.create_search(f"ls{i:03}", f"query {i}", "cat", "global")
        rows = _db.list_searches(limit=10)
        ids = {r["id"] for r in rows}
        assert {"ls000", "ls001", "ls002"}.issubset(ids)

    def test_list_searches_respects_limit(self):
        import db as _db
        for i in range(5):
            _db.create_search(f"lim{i:03}", f"q{i}", "cat", "global")
        rows = _db.list_searches(limit=2)
        assert len(rows) == 2

    def test_corrupt_json_column_returns_none(self):
        import db as _db
        import sqlite3
        _db.create_search("s-corrupt", "query", "cat", "global")
        # Manually inject corrupt JSON
        conn = _db._sqlite_connect()
        conn.execute("UPDATE Search SET analysis = ? WHERE id = ?", ("{NOT JSON}", "s-corrupt"))
        conn.commit()
        row = _db.get_search("s-corrupt")
        assert row["analysis"] is None  # must not raise


# ── Profile CRUD ──────────────────────────────────────────────────────────────

class TestProfileCrud:
    def test_save_and_get_profile(self):
        import db as _db
        data = {"preferences_summary": "needs budget earbuds", "interview": []}
        _db.save_profile_db("electronics/earbuds", data)
        loaded = _db.get_profile("electronics/earbuds")
        assert loaded is not None
        assert loaded["preferences_summary"] == "needs budget earbuds"

    def test_get_nonexistent_profile_returns_none(self):
        import db as _db
        assert _db.get_profile("nonexistent/category") is None

    def test_save_profile_upsert(self):
        import db as _db
        _db.save_profile_db("cat", {"v": 1})
        _db.save_profile_db("cat", {"v": 2})
        loaded = _db.get_profile("cat")
        assert loaded["v"] == 2

    def test_save_non_dict_raises(self):
        import db as _db
        with pytest.raises(ValueError):
            _db.save_profile_db("cat", "not a dict")


# ── UserSignal CRUD ───────────────────────────────────────────────────────────

class TestUserSignalCrud:
    def test_save_and_list_signal(self):
        import db as _db
        _db.save_signal("sig001", "preference", "loves ANC", category="electronics/earbuds")
        signals = _db.list_signals()
        assert any(s["id"] == "sig001" for s in signals)

    def test_delete_signal(self):
        import db as _db
        _db.save_signal("sig002", "preference", "hates bass", category="cat")
        deleted = _db.delete_signal("sig002")
        assert deleted is True
        signals = _db.list_signals()
        assert not any(s["id"] == "sig002" for s in signals)

    def test_clear_signals(self):
        import db as _db
        for i in range(3):
            _db.save_signal(f"sig-clr-{i}", "preference", f"text {i}")
        count = _db.clear_signals()
        assert count >= 3
        assert _db.list_signals() == []

    def test_save_signals_batch(self):
        import db as _db
        signals = [
            {"signal_id": f"batch-{i}", "signal_type": "preference", "text": f"text {i}"}
            for i in range(5)
        ]
        inserted = _db.save_signals_batch(signals)
        assert inserted == 5
        all_signals = _db.list_signals()
        assert len(all_signals) == 5

    def test_save_signals_batch_empty(self):
        import db as _db
        assert _db.save_signals_batch([]) == 0

    def test_save_signals_batch_dedup_on_conflict(self):
        """ON CONFLICT DO NOTHING — same signal_id not double-inserted."""
        import db as _db
        sigs = [{"signal_id": "dup-1", "signal_type": "preference", "text": "text"}]
        _db.save_signals_batch(sigs)
        _db.save_signals_batch(sigs)
        all_signals = _db.list_signals()
        dup_count = sum(1 for s in all_signals if s["id"] == "dup-1")
        assert dup_count == 1


# ── ProductMemory CRUD ────────────────────────────────────────────────────────

class TestProductMemoryCrud:
    def test_save_and_get(self):
        import db as _db
        _db.save_product_memory("Sony WF-1000XM5", "electronics/earbuds", status="considered")
        mem = _db.get_product_memory("Sony WF-1000XM5")
        assert mem is not None
        assert mem["status"] == "considered"

    def test_get_nonexistent_returns_none(self):
        import db as _db
        assert _db.get_product_memory("Phantom Product") is None

    def test_upsert_updates_status(self):
        import db as _db
        _db.save_product_memory("Widget X", "cat", status="considered")
        _db.save_product_memory("Widget X", "cat", status="purchased")
        mem = _db.get_product_memory("Widget X")
        assert mem["status"] == "purchased"

    def test_canonical_name_lookup(self):
        """Punctuation variants of the same product resolve to the same memory entry."""
        import db as _db
        _db.save_product_memory("Sony WF-1000XM5", "cat", status="rejected")
        # Lookup with spaces instead of hyphens
        mem = _db.get_product_memory("Sony WF1000XM5")
        assert mem is not None
        assert mem["status"] == "rejected"

    def test_delete_product_memory(self):
        import db as _db
        _db.save_product_memory("Delete Me", "cat")
        assert _db.delete_product_memory("Delete Me") is True
        assert _db.get_product_memory("Delete Me") is None

    def test_list_product_memories(self):
        import db as _db
        for name in ("Product A", "Product B", "Product C"):
            _db.save_product_memory(name, "cat")
        mems = _db.list_product_memories()
        names = {m["productName"] for m in mems}
        assert {"Product A", "Product B", "Product C"}.issubset(names)

    def test_clear_product_memories(self):
        import db as _db
        for name in ("X1", "X2"):
            _db.save_product_memory(name, "cat")
        count = _db.clear_product_memories()
        assert count >= 2
        assert _db.list_product_memories() == []


# ── close_db_connection ───────────────────────────────────────────────────────

class TestCloseDbConnection:
    def test_close_and_reopen(self):
        import db as _db
        _db._sqlite_connect()  # open
        _db.close_db_connection()  # close
        assert _db._local.conn is None
        # Next operation should re-open transparently
        conn = _db._sqlite_connect()
        assert conn is not None

    def test_close_when_no_connection_is_safe(self):
        import db as _db
        _db.close_db_connection()  # already closed — must not raise
        _db.close_db_connection()  # idempotent
