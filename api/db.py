"""
Database persistence layer — supports both Postgres (primary) and SQLite (fallback).

Decision: if POSTGRES_URL is set in the environment, use psycopg2 for all tables.
Otherwise use SQLite at web/prisma/shopping.db (existing v6 behavior).

Tables managed here:
  Search       — pipeline runs with results
  Profile      — per-category user preferences
  UserSignal   — extracted user preference signals with embeddings
  ProductMemory — products the user has considered/bought/rejected
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Load .env before reading any env vars — POSTGRES_URL is evaluated at module
# import time, so dotenv must be loaded here (not in main.py which imports us).
from dotenv import load_dotenv
load_dotenv()

_ROOT = Path(__file__).parent.parent
_SQLITE_PATH = _ROOT / "web" / "prisma" / "shopping.db"

POSTGRES_URL = os.environ.get("POSTGRES_URL", "")

# Thread-local SQLite connections (SQLite is not thread-safe across connections)
_local = threading.local()

# Postgres connection pool (lazy-initialized)
_pg_pool = None
_pg_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Backend selection helpers
# ---------------------------------------------------------------------------

def _use_postgres() -> bool:
    return bool(POSTGRES_URL)


def _pg_connect():
    """Return a psycopg2 connection from the pool (or create if first time)."""
    global _pg_pool
    try:
        import psycopg2
        import psycopg2.pool
    except ImportError:
        raise RuntimeError(
            "psycopg2 not installed. Run: pip install psycopg2-binary"
        )

    with _pg_lock:
        if _pg_pool is None:
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=10, dsn=POSTGRES_URL
            )
    return _pg_pool.getconn()


def _pg_release(conn) -> None:
    if _pg_pool is not None:
        _pg_pool.putconn(conn)


@contextmanager
def _pg_transaction():
    """Yield a psycopg2 cursor; commit on clean exit, rollback on exception, always release connection."""
    conn = _pg_connect()
    cur = None
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        _pg_release(conn)


def _sqlite_connect() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS Search (
    id          TEXT PRIMARY KEY,
    query       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    region      TEXT NOT NULL DEFAULT 'global',
    status      TEXT NOT NULL DEFAULT 'pending',
    createdAt   TEXT NOT NULL,
    profile     TEXT,
    rubric      TEXT,
    analysis    TEXT,
    scoredProducts TEXT,
    explanations   TEXT,
    shoppingLinks  TEXT
);

CREATE TABLE IF NOT EXISTS Profile (
    category    TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updatedAt   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS UserSignal (
    id             TEXT PRIMARY KEY,
    userId         TEXT NOT NULL DEFAULT 'default',
    signalType     TEXT NOT NULL,
    productName    TEXT,
    category       TEXT,
    text           TEXT NOT NULL,
    embedding      TEXT,
    strength       TEXT NOT NULL DEFAULT 'moderate',
    sourceSearchId TEXT,
    createdAt      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ProductMemory (
    id           TEXT PRIMARY KEY,
    userId       TEXT NOT NULL DEFAULT 'default',
    productName  TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'considered',
    ourScore     REAL,
    userFeedback TEXT,
    createdAt    TEXT NOT NULL,
    UNIQUE(userId, productName)
);
"""

_PG_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS "Search" (
    id          TEXT PRIMARY KEY,
    query       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    region      TEXT NOT NULL DEFAULT 'global',
    status      TEXT NOT NULL DEFAULT 'pending',
    "createdAt" TIMESTAMPTZ NOT NULL DEFAULT now(),
    profile     TEXT,
    rubric      TEXT,
    analysis    TEXT,
    "scoredProducts" TEXT,
    explanations     TEXT,
    "shoppingLinks"  TEXT
);

CREATE TABLE IF NOT EXISTS "Profile" (
    category    TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS "UserSignal" (
    id              TEXT PRIMARY KEY,
    "userId"        TEXT NOT NULL DEFAULT 'default',
    "signalType"    TEXT NOT NULL,
    "productName"   TEXT,
    category        TEXT,
    text            TEXT NOT NULL,
    embedding       vector(768),
    strength        TEXT NOT NULL DEFAULT 'moderate',
    "sourceSearchId" TEXT,
    "createdAt"     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS "ProductMemory" (
    id              TEXT PRIMARY KEY,
    "userId"        TEXT NOT NULL DEFAULT 'default',
    "productName"   TEXT NOT NULL,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'considered',
    "ourScore"      DOUBLE PRECISION,
    "userFeedback"  TEXT,
    "createdAt"     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE("userId", "productName")
);
"""


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(_PG_SCHEMA)
    else:
        conn = _sqlite_connect()
        conn.executescript(_SQLITE_SCHEMA)
        conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _cuid() -> str:
    import uuid
    return "c" + uuid.uuid4().hex[:24]


_JSON_SEARCH_FIELDS = {"profile", "rubric", "analysis", "scoredProducts", "explanations", "shoppingLinks"}


def _serialize(k: str, v: Any) -> Any:
    if k in _JSON_SEARCH_FIELDS and v is not None and not isinstance(v, str):
        return json.dumps(v)
    return v


def _deserialize_search(row: dict) -> dict:
    for col in _JSON_SEARCH_FIELDS:
        raw = row.get(col)
        if isinstance(raw, str):
            try:
                row[col] = json.loads(raw)
            except Exception:
                row[col] = None
    return row


# ---------------------------------------------------------------------------
# SQLite row helpers
# ---------------------------------------------------------------------------

def _sqlite_row_to_dict(row) -> dict:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)


# ---------------------------------------------------------------------------
# Postgres row helpers
# ---------------------------------------------------------------------------

def _pg_fetchone_as_dict(cur) -> Optional[dict]:
    if cur.description is None:
        return None
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _pg_fetchall_as_dict(cur) -> list[dict]:
    if cur.description is None:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Search CRUD
# ---------------------------------------------------------------------------

def create_search(search_id: str, query: str, category: str = "", region: str = "global") -> None:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                """INSERT INTO "Search" (id, query, category, region, status, "createdAt")
                   VALUES (%s, %s, %s, %s, %s, now()) ON CONFLICT DO NOTHING""",
                (search_id, query, category, region, "pending"),
            )
    else:
        conn = _sqlite_connect()
        conn.execute(
            "INSERT OR IGNORE INTO Search (id, query, category, region, status, createdAt) VALUES (?,?,?,?,?,?)",
            (search_id, query, category, region, "pending", _now_iso()),
        )
        conn.commit()


def update_search(search_id: str, **fields) -> None:
    if not fields:
        return
    if _use_postgres():
        with _pg_transaction() as cur:
            parts = []
            values = []
            for k, v in fields.items():
                # Map camelCase to quoted column names
                col = f'"{k}"' if k in ("scoredProducts", "shoppingLinks", "createdAt") else k
                parts.append(f"{col} = %s")
                values.append(_serialize(k, v))
            values.append(search_id)
            cur.execute(
                f'UPDATE "Search" SET {", ".join(parts)} WHERE id = %s', values
            )
    else:
        conn = _sqlite_connect()
        set_parts = []
        values = []
        for k, v in fields.items():
            set_parts.append(f"{k} = ?")
            values.append(_serialize(k, v))
        values.append(search_id)
        conn.execute(f"UPDATE Search SET {', '.join(set_parts)} WHERE id = ?", values)
        conn.commit()


def get_search(search_id: str) -> Optional[dict]:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute('SELECT * FROM "Search" WHERE id = %s', (search_id,))
            row = _pg_fetchone_as_dict(cur)
            return _deserialize_search(row) if row else None
    else:
        conn = _sqlite_connect()
        row = conn.execute("SELECT * FROM Search WHERE id = ?", (search_id,)).fetchone()
        return _deserialize_search(_sqlite_row_to_dict(row)) if row else None


def list_searches(limit: int = 50, offset: int = 0) -> list[dict]:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'SELECT * FROM "Search" ORDER BY "createdAt" DESC LIMIT %s OFFSET %s',
                (limit, offset),
            )
            rows = _pg_fetchall_as_dict(cur)
            return [_deserialize_search(r) for r in rows]
    else:
        conn = _sqlite_connect()
        rows = conn.execute(
            "SELECT * FROM Search ORDER BY createdAt DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_deserialize_search(_sqlite_row_to_dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

def get_profile(category: str) -> Optional[dict]:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute('SELECT data FROM "Profile" WHERE category = %s', (category,))
            row = cur.fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except Exception:
                    return None
            return None
    else:
        conn = _sqlite_connect()
        row = conn.execute("SELECT data FROM Profile WHERE category = ?", (category,)).fetchone()
        if row:
            try:
                return json.loads(row["data"])
            except Exception:
                return None
        return None


def save_profile_db(category: str, data: dict) -> None:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'INSERT INTO "Profile" (category, data, "updatedAt") VALUES (%s, %s, now()) '
                'ON CONFLICT (category) DO UPDATE SET data = EXCLUDED.data, "updatedAt" = now()',
                (category, json.dumps(data)),
            )
    else:
        conn = _sqlite_connect()
        conn.execute(
            "INSERT OR REPLACE INTO Profile (category, data, updatedAt) VALUES (?,?,?)",
            (category, json.dumps(data), _now_iso()),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# UserSignal CRUD
# ---------------------------------------------------------------------------

def save_signal(
    signal_id: str,
    signal_type: str,
    text: str,
    embedding: Optional[list[float]] = None,
    category: Optional[str] = None,
    product_name: Optional[str] = None,
    strength: str = "moderate",
    source_search_id: Optional[str] = None,
    user_id: str = "default",
) -> None:
    if _use_postgres():
        with _pg_transaction() as cur:
            emb_val = None
            if embedding:
                # pgvector accepts a Python list directly as array literal
                emb_val = "[" + ",".join(str(x) for x in embedding) + "]"
            cur.execute(
                """INSERT INTO "UserSignal"
                   (id, "userId", "signalType", "productName", category, text,
                    embedding, strength, "sourceSearchId", "createdAt")
                   VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, now())
                   ON CONFLICT DO NOTHING""",
                (signal_id, user_id, signal_type, product_name, category, text,
                 emb_val, strength, source_search_id),
            )
    else:
        conn = _sqlite_connect()
        emb_json = json.dumps(embedding) if embedding else None
        conn.execute(
            """INSERT OR IGNORE INTO UserSignal
               (id, userId, signalType, productName, category, text,
                embedding, strength, sourceSearchId, createdAt)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (signal_id, user_id, signal_type, product_name, category, text,
             emb_json, strength, source_search_id, _now_iso()),
        )
        conn.commit()


def list_signals(user_id: str = "default", limit: int = 200) -> list[dict]:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'SELECT id, "userId", "signalType", "productName", category, text, '
                '       strength, "sourceSearchId", "createdAt" '
                'FROM "UserSignal" WHERE "userId" = %s ORDER BY "createdAt" DESC LIMIT %s',
                (user_id, limit),
            )
            return _pg_fetchall_as_dict(cur)
    else:
        conn = _sqlite_connect()
        rows = conn.execute(
            "SELECT id, userId, signalType, productName, category, text, "
            "       strength, sourceSearchId, createdAt "
            "FROM UserSignal WHERE userId = ? ORDER BY createdAt DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [_sqlite_row_to_dict(r) for r in rows]


def find_similar_signals(
    query_embedding: list[float],
    k: int = 5,
    min_similarity: float = 0.7,
    user_id: str = "default",
) -> list[dict]:
    """
    Retrieve the k most similar signals using pgvector cosine distance (if Postgres)
    or in-memory cosine scan (if SQLite fallback).
    Returns list of dicts with a 'similarity' field added.
    """
    if _use_postgres():
        with _pg_transaction() as cur:
            emb_val = "[" + ",".join(str(x) for x in query_embedding) + "]"
            cur.execute(
                """SELECT id, "userId", "signalType", "productName", category, text,
                          strength, "sourceSearchId", "createdAt",
                          1 - (embedding <=> %s::vector) AS similarity
                   FROM "UserSignal"
                   WHERE "userId" = %s AND embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector
                   LIMIT %s""",
                (emb_val, user_id, emb_val, k * 2),
            )
            rows = _pg_fetchall_as_dict(cur)
            return [r for r in rows if (r.get("similarity") or 0.0) >= min_similarity][:k]
    else:
        # Linear cosine scan (fine for < 10k signals)
        from embeddings import cosine_similarity
        conn = _sqlite_connect()
        rows = conn.execute(
            "SELECT id, userId AS \"userId\", signalType AS \"signalType\", "
            "       productName AS \"productName\", category, text, "
            "       strength, sourceSearchId AS \"sourceSearchId\", "
            "       createdAt AS \"createdAt\", embedding "
            "FROM UserSignal WHERE userId = ? AND embedding IS NOT NULL LIMIT 2000",
            (user_id,),
        ).fetchall()

        scored = []
        for row in rows:
            d = _sqlite_row_to_dict(row)
            try:
                emb = json.loads(d.pop("embedding", "null") or "null")
            except Exception:
                emb = None
            if not emb:
                continue
            sim = cosine_similarity(query_embedding, emb)
            if sim >= min_similarity:
                d["similarity"] = sim
                scored.append(d)

        scored.sort(key=lambda x: -x["similarity"])
        return scored[:k]


def delete_signal(signal_id: str, user_id: str = "default") -> bool:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'DELETE FROM "UserSignal" WHERE id = %s AND "userId" = %s',
                (signal_id, user_id),
            )
            return cur.rowcount > 0
    else:
        conn = _sqlite_connect()
        cur = conn.execute("DELETE FROM UserSignal WHERE id = ? AND userId = ?", (signal_id, user_id))
        conn.commit()
        return cur.rowcount > 0


def clear_signals(user_id: str = "default") -> int:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute('DELETE FROM "UserSignal" WHERE "userId" = %s', (user_id,))
            return cur.rowcount
    else:
        conn = _sqlite_connect()
        cur = conn.execute("DELETE FROM UserSignal WHERE userId = ?", (user_id,))
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# ProductMemory CRUD
# ---------------------------------------------------------------------------

def save_product_memory(
    product_name: str,
    category: str,
    status: str = "considered",
    our_score: Optional[float] = None,
    user_feedback: Optional[str] = None,
    user_id: str = "default",
) -> None:
    mem_id = _cuid()
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                """INSERT INTO "ProductMemory"
                   (id, "userId", "productName", category, status, "ourScore",
                    "userFeedback", "createdAt")
                   VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                   ON CONFLICT ("userId", "productName")
                   DO UPDATE SET status = EXCLUDED.status,
                                 "ourScore" = COALESCE(EXCLUDED."ourScore", "ProductMemory"."ourScore"),
                                 "userFeedback" = COALESCE(EXCLUDED."userFeedback", "ProductMemory"."userFeedback")""",
                (mem_id, user_id, product_name, category, status, our_score, user_feedback),
            )
    else:
        conn = _sqlite_connect()
        existing = conn.execute(
            "SELECT id FROM ProductMemory WHERE userId = ? AND productName = ?",
            (user_id, product_name),
        ).fetchone()
        if existing:
            updates = ["status = ?"]
            vals: list = [status]
            if our_score is not None:
                updates.append("ourScore = ?")
                vals.append(our_score)
            if user_feedback is not None:
                updates.append("userFeedback = ?")
                vals.append(user_feedback)
            vals += [user_id, product_name]
            conn.execute(f"UPDATE ProductMemory SET {', '.join(updates)} WHERE userId = ? AND productName = ?", vals)
        else:
            conn.execute(
                "INSERT OR IGNORE INTO ProductMemory "
                "(id, userId, productName, category, status, ourScore, userFeedback, createdAt) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (mem_id, user_id, product_name, category, status, our_score, user_feedback, _now_iso()),
            )
        conn.commit()


def get_product_memory(product_name: str, user_id: str = "default") -> Optional[dict]:
    # Case-insensitive + prefix-tolerant matching: "Sony WF-1000XM5" matches
    # "Sony WF-1000XM5 Wireless Earbuds" stored from a previous search, and vice versa.
    name_lower = product_name.strip().lower()
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'SELECT * FROM "ProductMemory" '
                'WHERE "userId" = %s AND ('
                '  LOWER("productName") = %s'
                '  OR LOWER(%s) LIKE LOWER("productName") || \' %%\''
                '  OR LOWER("productName") LIKE LOWER(%s) || \' %%\''
                ') LIMIT 1',
                (user_id, name_lower, product_name, product_name),
            )
            return _pg_fetchone_as_dict(cur)
    else:
        conn = _sqlite_connect()
        row = conn.execute(
            "SELECT * FROM ProductMemory "
            "WHERE userId = ? AND ("
            "  LOWER(productName) = ?"
            "  OR LOWER(?) LIKE LOWER(productName) || ' %'"
            "  OR LOWER(productName) LIKE LOWER(?) || ' %'"
            ") LIMIT 1",
            (user_id, name_lower, product_name, product_name),
        ).fetchone()
        return _sqlite_row_to_dict(row) if row else None


def list_product_memories(user_id: str = "default", limit: int = 100) -> list[dict]:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'SELECT * FROM "ProductMemory" WHERE "userId" = %s ORDER BY "createdAt" DESC LIMIT %s',
                (user_id, limit),
            )
            return _pg_fetchall_as_dict(cur)
    else:
        conn = _sqlite_connect()
        rows = conn.execute(
            "SELECT * FROM ProductMemory WHERE userId = ? ORDER BY createdAt DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [_sqlite_row_to_dict(r) for r in rows]


def delete_product_memory(product_name: str, user_id: str = "default") -> bool:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'DELETE FROM "ProductMemory" WHERE "userId" = %s AND "productName" = %s',
                (user_id, product_name),
            )
            return cur.rowcount > 0
    else:
        conn = _sqlite_connect()
        cur = conn.execute(
            "DELETE FROM ProductMemory WHERE userId = ? AND productName = ?",
            (user_id, product_name),
        )
        conn.commit()
        return cur.rowcount > 0


def clear_product_memories(user_id: str = "default") -> int:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute('DELETE FROM "ProductMemory" WHERE "userId" = %s', (user_id,))
            return cur.rowcount
    else:
        conn = _sqlite_connect()
        cur = conn.execute("DELETE FROM ProductMemory WHERE userId = ?", (user_id,))
        conn.commit()
        return cur.rowcount
