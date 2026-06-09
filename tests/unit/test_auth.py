"""
Unit tests for authentication and user-ID scoping.

Tests are split into two groups:
 1. Pure-logic tests — mirror the auth functions from main.py without importing
    the full app (which has a deep import chain). These test the algorithm.
 2. Real-DB tests — use the actual api/db.py module with an in-memory SQLite DB
    to verify user_id column writes and reads.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import time
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))


# ---------------------------------------------------------------------------
# Load the real db module from api/db.py (for DB-level tests only)
# ---------------------------------------------------------------------------

def _load_real_db():
    if "dotenv" not in sys.modules:
        m = types.ModuleType("dotenv")
        m.load_dotenv = lambda *a, **kw: None
        sys.modules["dotenv"] = m
    db_path = _ROOT / "api" / "db.py"
    spec = importlib.util.spec_from_file_location("_real_db_module", str(db_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_REAL_DB = _load_real_db()


# ---------------------------------------------------------------------------
# Inline implementations of main.py auth functions (no app import needed)
# These mirror the exact code in api/main.py so the tests stay valid.
# ---------------------------------------------------------------------------

def _get_session_user_id(headers: dict) -> str:
    sid = headers.get("X-Session-ID", "").strip()
    if sid and len(sid) <= 64 and sid.replace("-", "").replace("_", "").isalnum():
        return sid
    return "default"


def _verify_auth_token(headers: dict, secret: str, has_pyjwt: bool) -> str | None:
    auth_header = headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    if not secret:
        return None
    if not has_pyjwt:
        return None
    try:
        import jwt as _jwt
        payload = _jwt.decode(token, secret, algorithms=["HS256"])
        sub = payload.get("sub")
        if not sub:
            return None
        return f"auth_{sub}"
    except Exception:
        return None


def _get_user_id(headers: dict, secret: str, has_pyjwt: bool) -> str:
    auth_user = _verify_auth_token(headers, secret, has_pyjwt)
    if auth_user:
        return auth_user
    return _get_session_user_id(headers)


def _require_auth(headers: dict, secret: str, has_pyjwt: bool) -> str:
    uid = _get_user_id(headers, secret, has_pyjwt)
    if not uid.startswith("auth_"):
        raise ValueError("401: Please log in to access this resource")
    return uid


# ---------------------------------------------------------------------------
# Helper to make a JWT token
# ---------------------------------------------------------------------------

def _make_jwt(secret: str, sub: str = "user123", expired: bool = False) -> str:
    try:
        import jwt as _jwt
    except ImportError:
        pytest.skip("PyJWT not installed")
    payload: dict = {"sub": sub}
    if expired:
        payload["exp"] = int(time.time()) - 3600
    return _jwt.encode(payload, secret, algorithm="HS256")


# ═══════════════════════════════════════════════════════════════════════════
# _get_session_user_id
# ═══════════════════════════════════════════════════════════════════════════

class TestGetSessionUserId:
    def test_valid_ss_prefix_returned(self):
        assert _get_session_user_id({"X-Session-ID": "ss_abc123def456"}) == "ss_abc123def456"

    def test_plain_id_returned_unchanged(self):
        assert _get_session_user_id({"X-Session-ID": "abc123"}) == "abc123"

    def test_missing_header_returns_default(self):
        assert _get_session_user_id({}) == "default"

    def test_too_long_id_returns_default(self):
        assert _get_session_user_id({"X-Session-ID": "a" * 65}) == "default"

    def test_special_chars_returns_default(self):
        assert _get_session_user_id({"X-Session-ID": "../../etc/passwd"}) == "default"

    def test_empty_string_returns_default(self):
        assert _get_session_user_id({"X-Session-ID": ""}) == "default"

    def test_exactly_64_chars_accepted(self):
        sid = "a" * 64
        assert _get_session_user_id({"X-Session-ID": sid}) == sid

    def test_spaces_in_id_returns_default(self):
        assert _get_session_user_id({"X-Session-ID": "ss abc"}) == "default"


# ═══════════════════════════════════════════════════════════════════════════
# _verify_auth_token
# ═══════════════════════════════════════════════════════════════════════════

class TestVerifyAuthToken:
    SECRET = "test-secret-abc"

    def test_valid_token_returns_auth_user(self):
        token = _make_jwt(self.SECRET)
        uid = _verify_auth_token({"Authorization": f"Bearer {token}"}, self.SECRET, True)
        assert uid == "auth_user123"

    def test_no_auth_header_returns_none(self):
        assert _verify_auth_token({}, self.SECRET, True) is None

    def test_non_bearer_header_returns_none(self):
        assert _verify_auth_token({"Authorization": "Basic xyz"}, self.SECRET, True) is None

    def test_empty_secret_returns_none(self):
        token = _make_jwt(self.SECRET)
        assert _verify_auth_token({"Authorization": f"Bearer {token}"}, "", True) is None

    def test_pyjwt_not_installed_returns_none(self):
        assert _verify_auth_token({"Authorization": "Bearer sometoken"}, self.SECRET, False) is None

    def test_garbage_token_returns_none(self):
        assert _verify_auth_token({"Authorization": "Bearer not.a.valid.jwt"}, self.SECRET, True) is None

    def test_wrong_secret_returns_none(self):
        token = _make_jwt("correct-secret")
        assert _verify_auth_token({"Authorization": f"Bearer {token}"}, "wrong-secret", True) is None

    def test_expired_token_returns_none(self):
        token = _make_jwt(self.SECRET, expired=True)
        assert _verify_auth_token({"Authorization": f"Bearer {token}"}, self.SECRET, True) is None

    def test_token_missing_sub_returns_none(self):
        try:
            import jwt as _jwt
        except ImportError:
            pytest.skip("PyJWT not installed")
        token = _jwt.encode({}, self.SECRET, algorithm="HS256")
        assert _verify_auth_token({"Authorization": f"Bearer {token}"}, self.SECRET, True) is None

    def test_different_subs_produce_different_user_ids(self):
        t1 = _make_jwt(self.SECRET, sub="alice")
        t2 = _make_jwt(self.SECRET, sub="bob")
        assert _verify_auth_token({"Authorization": f"Bearer {t1}"}, self.SECRET, True) == "auth_alice"
        assert _verify_auth_token({"Authorization": f"Bearer {t2}"}, self.SECRET, True) == "auth_bob"


# ═══════════════════════════════════════════════════════════════════════════
# _get_user_id — auth takes priority over session header
# ═══════════════════════════════════════════════════════════════════════════

class TestGetUserId:
    SECRET = "test-secret-abc"

    def test_authenticated_user_overrides_session_id(self):
        token = _make_jwt(self.SECRET)
        uid = _get_user_id(
            {"Authorization": f"Bearer {token}", "X-Session-ID": "ss_guest123"},
            self.SECRET, True,
        )
        assert uid == "auth_user123"

    def test_no_auth_falls_back_to_session_id(self):
        assert _get_user_id({"X-Session-ID": "ss_abc"}, self.SECRET, True) == "ss_abc"

    def test_no_auth_no_session_returns_default(self):
        assert _get_user_id({}, self.SECRET, True) == "default"

    def test_invalid_token_falls_back_to_session_id(self):
        uid = _get_user_id(
            {"Authorization": "Bearer garbage", "X-Session-ID": "ss_fallback"},
            self.SECRET, True,
        )
        assert uid == "ss_fallback"


# ═══════════════════════════════════════════════════════════════════════════
# _require_auth — raises for guests
# ═══════════════════════════════════════════════════════════════════════════

class TestRequireAuth:
    SECRET = "test-secret-abc"

    def test_authenticated_request_passes(self):
        token = _make_jwt(self.SECRET)
        uid = _require_auth({"Authorization": f"Bearer {token}"}, self.SECRET, True)
        assert uid == "auth_user123"

    def test_guest_session_raises(self):
        with pytest.raises(ValueError, match="401"):
            _require_auth({"X-Session-ID": "ss_guest"}, self.SECRET, True)

    def test_no_headers_raises(self):
        with pytest.raises(ValueError, match="401"):
            _require_auth({}, self.SECRET, True)

    def test_invalid_token_raises(self):
        with pytest.raises(ValueError, match="401"):
            _require_auth({"Authorization": "Bearer junk"}, self.SECRET, True)

    def test_expired_token_raises(self):
        token = _make_jwt(self.SECRET, expired=True)
        with pytest.raises(ValueError, match="401"):
            _require_auth({"Authorization": f"Bearer {token}"}, self.SECRET, True)


# ═══════════════════════════════════════════════════════════════════════════
# db.create_search / list_searches — user_id round-trip (real db module)
# ═══════════════════════════════════════════════════════════════════════════

def _make_search_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE Search (
            id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            category TEXT DEFAULT '',
            region TEXT DEFAULT 'global',
            status TEXT DEFAULT 'pending',
            userId TEXT NOT NULL DEFAULT 'default',
            createdAt TEXT NOT NULL,
            profile TEXT, rubric TEXT, analysis TEXT,
            scoredProducts TEXT, shoppingLinks TEXT
        )
    """)
    conn.commit()
    return conn


class TestDbSearchUserScoping:
    def test_create_search_stores_user_id(self):
        conn = _make_search_db()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn), \
             patch.object(_REAL_DB, "_now_iso", return_value="2026-01-01T00:00:00Z"):
            _REAL_DB.create_search("s1", "q", "cat", "global", "auth_u1")
        assert conn.execute("SELECT userId FROM Search WHERE id='s1'").fetchone()["userId"] == "auth_u1"

    def test_create_search_default_user_id(self):
        conn = _make_search_db()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn), \
             patch.object(_REAL_DB, "_now_iso", return_value="2026-01-01T00:00:00Z"):
            _REAL_DB.create_search("s2", "query")
        assert conn.execute("SELECT userId FROM Search WHERE id='s2'").fetchone()["userId"] == "default"

    def test_list_searches_scoped_to_user(self):
        conn = _make_search_db()
        now = "2026-01-01T00:00:00Z"
        conn.execute("INSERT INTO Search (id,query,userId,createdAt) VALUES (?,?,?,?)", ("s1","q1","auth_a",now))
        conn.execute("INSERT INTO Search (id,query,userId,createdAt) VALUES (?,?,?,?)", ("s2","q2","auth_b",now))
        conn.commit()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn):
            ra = _REAL_DB.list_searches(user_id="auth_a")
            rb = _REAL_DB.list_searches(user_id="auth_b")
            rd = _REAL_DB.list_searches(user_id="default")
        assert len(ra) == 1 and ra[0]["id"] == "s1"
        assert len(rb) == 1 and rb[0]["id"] == "s2"
        assert rd == []

    def test_list_searches_does_not_leak_across_users(self):
        conn = _make_search_db()
        now = "2026-01-01T00:00:00Z"
        for i in range(5):
            conn.execute("INSERT INTO Search (id,query,userId,createdAt) VALUES (?,?,?,?)",
                         (f"s{i}",f"q{i}","auth_x",now))
        conn.commit()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn):
            assert _REAL_DB.list_searches(user_id="auth_y") == []

    def test_list_searches_respects_limit(self):
        conn = _make_search_db()
        now = "2026-01-01T00:00:00Z"
        for i in range(10):
            conn.execute("INSERT INTO Search (id,query,userId,createdAt) VALUES (?,?,?,?)",
                         (f"s{i}",f"q{i}","auth_z",now))
        conn.commit()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn):
            assert len(_REAL_DB.list_searches(limit=3, user_id="auth_z")) == 3


# ═══════════════════════════════════════════════════════════════════════════
# db.reassign_user_data
# ═══════════════════════════════════════════════════════════════════════════

def _make_full_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE Search (
            id TEXT PRIMARY KEY, query TEXT,
            userId TEXT NOT NULL DEFAULT 'default', createdAt TEXT
        );
        CREATE TABLE UserSignal (
            id TEXT PRIMARY KEY, userId TEXT NOT NULL DEFAULT 'default',
            signalType TEXT, productName TEXT, category TEXT,
            text TEXT, strength TEXT, embedding BLOB,
            sourceSearchId TEXT, createdAt TEXT
        );
        CREATE TABLE ProductMemory (
            id TEXT PRIMARY KEY, userId TEXT NOT NULL DEFAULT 'default',
            productName TEXT, canonicalName TEXT, category TEXT,
            status TEXT, ourScore REAL, userFeedback TEXT, createdAt TEXT
        );
        CREATE TABLE Profile (
            id TEXT PRIMARY KEY, userId TEXT NOT NULL DEFAULT 'default',
            category TEXT, data TEXT, updatedAt TEXT
        );
    """)
    conn.commit()
    return conn


class TestReassignUserData:
    def test_reassign_moves_all_tables(self):
        conn = _make_full_db()
        conn.execute("INSERT INTO Search VALUES ('s1','q','ss_guest','2026-01-01')")
        conn.execute("INSERT INTO UserSignal VALUES ('sig1','ss_guest','pref','X','cat','text','strong',NULL,NULL,'2026-01-01')")
        conn.execute("INSERT INTO ProductMemory VALUES ('pm1','ss_guest','Prod X','prodx','cat','considered',8.0,NULL,'2026-01-01')")
        conn.commit()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn):
            counts = _REAL_DB.reassign_user_data("ss_guest", "auth_user999")
        assert conn.execute("SELECT userId FROM Search WHERE id='s1'").fetchone()["userId"] == "auth_user999"
        assert conn.execute("SELECT userId FROM UserSignal WHERE id='sig1'").fetchone()["userId"] == "auth_user999"
        assert conn.execute("SELECT userId FROM ProductMemory WHERE id='pm1'").fetchone()["userId"] == "auth_user999"
        assert isinstance(counts, dict)

    def test_reassign_noop_on_unknown_source(self):
        conn = _make_full_db()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn):
            counts = _REAL_DB.reassign_user_data("ss_nonexistent", "auth_user1")
        for t in ["Search", "UserSignal", "ProductMemory"]:
            assert conn.execute(f"SELECT * FROM {t}").fetchall() == []

    def test_reassign_leaves_other_users_untouched(self):
        conn = _make_full_db()
        conn.execute("INSERT INTO Search VALUES ('a','q','ss_guest','2026-01-01')")
        conn.execute("INSERT INTO Search VALUES ('b','q','auth_other','2026-01-01')")
        conn.commit()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn):
            _REAL_DB.reassign_user_data("ss_guest", "auth_new")
        assert conn.execute("SELECT userId FROM Search WHERE id='b'").fetchone()["userId"] == "auth_other"
        assert conn.execute("SELECT userId FROM Search WHERE id='a'").fetchone()["userId"] == "auth_new"

    def test_reassign_returns_row_counts(self):
        conn = _make_full_db()
        conn.execute("INSERT INTO Search VALUES ('s1','q','ss_guest','2026-01-01')")
        conn.execute("INSERT INTO UserSignal VALUES ('si1','ss_guest','pref','P','c','t','s',NULL,NULL,'2026-01-01')")
        conn.commit()
        with patch.object(_REAL_DB, "_use_postgres", return_value=False), \
             patch.object(_REAL_DB, "_sqlite_connect", return_value=conn):
            counts = _REAL_DB.reassign_user_data("ss_guest", "auth_new2")
        assert counts.get("Search", 0) == 1
        assert counts.get("UserSignal", 0) == 1
