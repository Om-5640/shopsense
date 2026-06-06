"""
Database persistence layer — supports both Postgres (primary) and SQLite (fallback).

Decision: if POSTGRES_URL is set in the environment, use psycopg2 for all tables.
Otherwise use SQLite at web/prisma/shopping.db (existing v6 behavior).

Tables managed here:
  Search       — pipeline runs with results
  Profile      — per-category user preferences
  UserSignal   — extracted user preference signals with embeddings
  ProductMemory — products the user has considered/bought/rejected
  _SchemaVersion — tracks applied migrations (lightweight Alembic alternative)
"""

import json
import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# Load .env before reading any env vars — POSTGRES_URL is evaluated at module
# import time, so dotenv must be loaded here (not in main.py which imports us).
from dotenv import load_dotenv
load_dotenv()

_logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_SQLITE_PATH = _ROOT / "web" / "prisma" / "shopping.db"

POSTGRES_URL = os.environ.get("POSTGRES_URL", "")

# Pool sizing — tune for your deployment without touching code
_PG_POOL_MIN = int(os.environ.get("PG_POOL_MIN", "1"))
_PG_POOL_MAX = int(os.environ.get("PG_POOL_MAX", "10"))

# How many SQLite rows to scan for cosine similarity (linear scan — trade RAM for recall)
_SIGNAL_SCAN_LIMIT = int(os.environ.get("SIGNAL_SCAN_LIMIT", "10000"))

# Thread-local SQLite connections (SQLite is not thread-safe across connections)
_local = threading.local()

# Postgres connection pool (lazy-initialized)
_pg_pool = None
_pg_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Canonical product name helper
# ---------------------------------------------------------------------------

def _canonical_product_name(name: str) -> str:
    """Strip all non-alphanumeric chars and lowercase — used for fuzzy match."""
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


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
                minconn=_PG_POOL_MIN, maxconn=_PG_POOL_MAX, dsn=POSTGRES_URL
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
        conn = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def close_db_connection() -> None:
    """Close and discard the calling thread's SQLite connection.

    Call this at the end of any long-lived worker thread (e.g., ThreadPoolExecutor
    tasks) to release the file handle. The next call to _sqlite_connect() on the
    same thread opens a fresh connection.  Safe to call when no connection exists.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


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

CREATE TABLE IF NOT EXISTS ShareToken (
    token       TEXT PRIMARY KEY,
    search_id   TEXT NOT NULL REFERENCES Search(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT
);

CREATE INDEX IF NOT EXISTS sharetoken_search_idx ON ShareToken (search_id);

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
    sourceSearchId TEXT REFERENCES Search(id) ON DELETE SET NULL,
    createdAt      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ProductMemory (
    id             TEXT PRIMARY KEY,
    userId         TEXT NOT NULL DEFAULT 'default',
    productName    TEXT NOT NULL,
    canonicalName  TEXT,
    category       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'considered',
    ourScore       REAL,
    userFeedback   TEXT,
    createdAt      TEXT NOT NULL,
    UNIQUE(userId, productName)
);

CREATE TABLE IF NOT EXISTS _SchemaVersion (
    version   INTEGER PRIMARY KEY,
    appliedAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS EmbeddingCache (
    hash        TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    provider    TEXT NOT NULL,
    embedding   TEXT NOT NULL,
    dims        INTEGER NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP DEFAULT (datetime('now', '+1 year'))
);

CREATE INDEX IF NOT EXISTS idx_ec_expires ON EmbeddingCache(expires_at);
CREATE INDEX IF NOT EXISTS idx_ec_created ON EmbeddingCache(created_at);

CREATE INDEX IF NOT EXISTS productmemory_canonical_idx
ON ProductMemory (userId, canonicalName);

CREATE INDEX IF NOT EXISTS usersignal_user_idx
ON UserSignal (userId, createdAt);
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
    "sourceSearchId" TEXT REFERENCES "Search"(id) ON DELETE SET NULL,
    "createdAt"     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS "ProductMemory" (
    id              TEXT PRIMARY KEY,
    "userId"        TEXT NOT NULL DEFAULT 'default',
    "productName"   TEXT NOT NULL,
    "canonicalName" TEXT,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'considered',
    "ourScore"      DOUBLE PRECISION,
    "userFeedback"  TEXT,
    "createdAt"     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE("userId", "productName")
);

CREATE TABLE IF NOT EXISTS "_SchemaVersion" (
    version     INTEGER PRIMARY KEY,
    "appliedAt" TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Self-heal: a ProductMemory table created by an older schema version lacks
-- canonicalName. CREATE TABLE IF NOT EXISTS is a no-op on the existing table, so
-- guarantee the column exists before the index below references it. Without this,
-- init_db() crashes on legacy databases before run_migrations() can patch it.
ALTER TABLE "ProductMemory" ADD COLUMN IF NOT EXISTS "canonicalName" TEXT;

CREATE INDEX IF NOT EXISTS productmemory_canonical_idx
ON "ProductMemory" ("userId", "canonicalName");

CREATE INDEX IF NOT EXISTS usersignal_user_idx
ON "UserSignal" ("userId", "createdAt" DESC);

CREATE TABLE IF NOT EXISTS "ShareToken" (
    token       TEXT PRIMARY KEY,
    search_id   TEXT NOT NULL REFERENCES "Search"(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sharetoken_search_idx ON "ShareToken" (search_id);

CREATE TABLE IF NOT EXISTS "EmbeddingCache" (
    hash        TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    provider    TEXT NOT NULL,
    embedding   TEXT NOT NULL,
    dims        INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '1 year')
);

CREATE INDEX IF NOT EXISTS idx_ec_expires ON "EmbeddingCache"(expires_at);
CREATE INDEX IF NOT EXISTS idx_ec_created ON "EmbeddingCache"(created_at);
"""


# ---------------------------------------------------------------------------
# Migration system
# ---------------------------------------------------------------------------

def _m1_sqlite_add_canonical_name() -> None:
    conn = _sqlite_connect()
    try:
        conn.execute("ALTER TABLE ProductMemory ADD COLUMN canonicalName TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Already exists — SQLite has no ADD COLUMN IF NOT EXISTS


def _m2_sqlite_add_fk_usersignal() -> None:
    """
    Recreate UserSignal with a real FK on sourceSearchId.
    Table recreation is the only way to add constraints in SQLite.
    Uses explicit BEGIN/COMMIT so the swap is atomic; PRAGMA foreign_keys
    is toggled outside any transaction as SQLite requires.
    SET NULL chosen over CASCADE: signals capture learned user preferences
    and remain valuable even when the originating search is deleted.
    """
    conn = _sqlite_connect()
    conn.executescript("""
        PRAGMA foreign_keys=OFF;
        BEGIN;
        CREATE TABLE IF NOT EXISTS _UserSignal_new (
            id             TEXT PRIMARY KEY,
            userId         TEXT NOT NULL DEFAULT 'default',
            signalType     TEXT NOT NULL,
            productName    TEXT,
            category       TEXT,
            text           TEXT NOT NULL,
            embedding      TEXT,
            strength       TEXT NOT NULL DEFAULT 'moderate',
            sourceSearchId TEXT REFERENCES Search(id) ON DELETE SET NULL,
            createdAt      TEXT NOT NULL
        );
        INSERT OR IGNORE INTO _UserSignal_new SELECT * FROM UserSignal;
        DROP TABLE IF EXISTS UserSignal;
        ALTER TABLE _UserSignal_new RENAME TO UserSignal;
        COMMIT;
        CREATE INDEX IF NOT EXISTS usersignal_user_idx ON UserSignal (userId, createdAt);
        PRAGMA foreign_keys=ON;
    """)


# Each entry: (version, description, sqlite_fn | None, pg_sql | None)
# Migrations are idempotent: safe to re-run if a previous attempt partially failed.
_MIGRATIONS: list[tuple[int, str, Optional[Callable], Optional[str]]] = [
    (
        1,
        "Add canonicalName column to ProductMemory",
        _m1_sqlite_add_canonical_name,
        'ALTER TABLE "ProductMemory" ADD COLUMN IF NOT EXISTS "canonicalName" TEXT',
    ),
    (
        2,
        "Add FK UserSignal.sourceSearchId → Search.id ON DELETE SET NULL",
        _m2_sqlite_add_fk_usersignal,
        # Postgres ADD CONSTRAINT IF NOT EXISTS is not supported; use DO block instead.
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_usersignal_search'
            ) THEN
                ALTER TABLE "UserSignal"
                ADD CONSTRAINT fk_usersignal_search
                FOREIGN KEY ("sourceSearchId") REFERENCES "Search"(id) ON DELETE SET NULL;
            END IF;
        END $$
        """,
    ),
]


def _current_schema_version() -> int:
    """Return the highest applied migration version (0 if table missing or empty)."""
    if _use_postgres():
        try:
            with _pg_transaction() as cur:
                cur.execute('SELECT COALESCE(MAX(version), 0) FROM "_SchemaVersion"')
                row = cur.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0
    else:
        try:
            row = _sqlite_connect().execute(
                "SELECT COALESCE(MAX(version), 0) FROM _SchemaVersion"
            ).fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0


def _mark_migration_applied(version: int) -> None:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'INSERT INTO "_SchemaVersion" (version, "appliedAt") VALUES (%s, now()) ON CONFLICT DO NOTHING',
                (version,),
            )
    else:
        conn = _sqlite_connect()
        conn.execute(
            "INSERT OR IGNORE INTO _SchemaVersion (version, appliedAt) VALUES (?,?)",
            (version, _now_iso()),
        )
        conn.commit()


def run_migrations() -> None:
    """Apply all pending schema migrations in version order."""
    current = _current_schema_version()
    for version, description, sqlite_fn, pg_sql in _MIGRATIONS:
        if version <= current:
            continue
        _logger.info("[db] Applying migration %d: %s", version, description)
        try:
            if _use_postgres():
                if pg_sql:
                    with _pg_transaction() as cur:
                        cur.execute(pg_sql)
            else:
                if sqlite_fn:
                    sqlite_fn()
            _mark_migration_applied(version)
            _logger.info("[db] Migration %d applied", version)
        except Exception as exc:
            _logger.warning("[db] Migration %d failed (may already be applied): %s", version, exc)


def _create_pg_vector_index() -> None:
    """
    Create HNSW cosine index on UserSignal.embedding.
    Must run outside a transaction (Postgres requirement for index methods).
    HNSW is preferred over IVFFlat: works on empty tables, no VACUUM/ANALYZE needed.
    """
    conn = _pg_connect()
    prev_autocommit = getattr(conn, "autocommit", False)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            'CREATE INDEX IF NOT EXISTS usersignal_embedding_idx '
            'ON "UserSignal" USING hnsw (embedding vector_cosine_ops)'
        )
        cur.close()
        _logger.info("[db] pgvector HNSW index ensured on UserSignal.embedding")
    except Exception as exc:
        _logger.warning(
            "[db] Could not create pgvector HNSW index (non-fatal — queries will still work via full scan): %s", exc
        )
    finally:
        conn.autocommit = prev_autocommit
        _pg_release(conn)


def init_db() -> None:
    """Create all tables and indexes if they don't exist, then apply pending migrations."""
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(_PG_SCHEMA)
        run_migrations()
        _create_pg_vector_index()
    else:
        conn = _sqlite_connect()
        conn.executescript(_SQLITE_SCHEMA)
        conn.commit()
        run_migrations()


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
            except Exception as exc:
                _logger.warning(
                    "[db] Corrupt JSON in column %r for search %s: %s",
                    col, row.get("id"), exc,
                )
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
                except Exception as exc:
                    _logger.warning("[db] Corrupt profile JSON for category %r: %s", category, exc)
                    return None
            return None
    else:
        conn = _sqlite_connect()
        row = conn.execute("SELECT data FROM Profile WHERE category = ?", (category,)).fetchone()
        if row:
            try:
                return json.loads(row["data"])
            except Exception as exc:
                _logger.warning("[db] Corrupt profile JSON for category %r: %s", category, exc)
                return None
        return None


def save_profile_db(category: str, data: Any) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"Profile data must be a dict, got {type(data).__name__!r}")
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


def save_signals_batch(signals: list[dict]) -> int:
    """
    Bulk-insert signals in a single transaction. Much faster than N save_signal calls.

    Each dict supports keys: signal_id, signal_type (required), text (required),
    embedding, category, product_name, strength, source_search_id, user_id.
    Returns the number of rows actually inserted.
    """
    if not signals:
        return 0
    inserted = 0
    if _use_postgres():
        with _pg_transaction() as cur:
            for s in signals:
                emb = s.get("embedding")
                emb_val = ("[" + ",".join(str(x) for x in emb) + "]") if emb else None
                cur.execute(
                    """INSERT INTO "UserSignal"
                       (id, "userId", "signalType", "productName", category, text,
                        embedding, strength, "sourceSearchId", "createdAt")
                       VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, now())
                       ON CONFLICT DO NOTHING""",
                    (
                        s.get("signal_id") or _cuid(),
                        s.get("user_id", "default"),
                        s["signal_type"],
                        s.get("product_name"),
                        s.get("category"),
                        s["text"],
                        emb_val,
                        s.get("strength", "moderate"),
                        s.get("source_search_id"),
                    ),
                )
                inserted += cur.rowcount
    else:
        conn = _sqlite_connect()
        now = _now_iso()
        cur = conn.cursor()
        for s in signals:
            emb = s.get("embedding")
            emb_json = json.dumps(emb) if emb else None
            cur.execute(
                """INSERT OR IGNORE INTO UserSignal
                   (id, userId, signalType, productName, category, text,
                    embedding, strength, sourceSearchId, createdAt)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    s.get("signal_id") or _cuid(),
                    s.get("user_id", "default"),
                    s["signal_type"],
                    s.get("product_name"),
                    s.get("category"),
                    s["text"],
                    emb_json,
                    s.get("strength", "moderate"),
                    s.get("source_search_id"),
                    now,
                ),
            )
            inserted += cur.rowcount
        conn.commit()
    return inserted


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
        # Linear cosine scan — configurable via SIGNAL_SCAN_LIMIT env var
        from embeddings import cosine_similarity
        conn = _sqlite_connect()
        rows = conn.execute(
            "SELECT id, userId AS \"userId\", signalType AS \"signalType\", "
            "       productName AS \"productName\", category, text, "
            "       strength, sourceSearchId AS \"sourceSearchId\", "
            "       createdAt AS \"createdAt\", embedding "
            "FROM UserSignal WHERE userId = ? AND embedding IS NOT NULL LIMIT ?",
            (user_id, _SIGNAL_SCAN_LIMIT),
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
    canonical = _canonical_product_name(product_name)
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                """INSERT INTO "ProductMemory"
                   (id, "userId", "productName", "canonicalName", category, status,
                    "ourScore", "userFeedback", "createdAt")
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                   ON CONFLICT ("userId", "productName")
                   DO UPDATE SET status = EXCLUDED.status,
                                 "canonicalName" = EXCLUDED."canonicalName",
                                 "ourScore" = COALESCE(EXCLUDED."ourScore", "ProductMemory"."ourScore"),
                                 "userFeedback" = COALESCE(EXCLUDED."userFeedback", "ProductMemory"."userFeedback")""",
                (mem_id, user_id, product_name, canonical, category, status, our_score, user_feedback),
            )
    else:
        conn = _sqlite_connect()
        existing = conn.execute(
            "SELECT id FROM ProductMemory WHERE userId = ? AND productName = ?",
            (user_id, product_name),
        ).fetchone()
        if existing:
            updates = ["status = ?", "canonicalName = ?"]
            vals: list = [status, canonical]
            if our_score is not None:
                updates.append("ourScore = ?")
                vals.append(our_score)
            if user_feedback is not None:
                updates.append("userFeedback = ?")
                vals.append(user_feedback)
            vals += [user_id, product_name]
            conn.execute(
                f"UPDATE ProductMemory SET {', '.join(updates)} WHERE userId = ? AND productName = ?",
                vals,
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO ProductMemory "
                "(id, userId, productName, canonicalName, category, status, ourScore, userFeedback, createdAt) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (mem_id, user_id, product_name, canonical, category, status, our_score, user_feedback, _now_iso()),
            )
        conn.commit()


def get_product_memory(product_name: str, user_id: str = "default") -> Optional[dict]:
    """
    Canonical-key lookup first (handles all spacing/punctuation/ordering variants),
    then exact original-name fallback for rows saved before canonicalization was added.
    """
    canonical = _canonical_product_name(product_name)
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'SELECT * FROM "ProductMemory" '
                'WHERE "userId" = %s AND "canonicalName" = %s LIMIT 1',
                (user_id, canonical),
            )
            row = _pg_fetchone_as_dict(cur)
            if row:
                return row
            # Fallback for legacy rows (no canonicalName stored)
            cur.execute(
                'SELECT * FROM "ProductMemory" '
                'WHERE "userId" = %s AND LOWER("productName") = LOWER(%s) LIMIT 1',
                (user_id, product_name),
            )
            return _pg_fetchone_as_dict(cur)
    else:
        conn = _sqlite_connect()
        row = conn.execute(
            "SELECT * FROM ProductMemory WHERE userId = ? AND canonicalName = ? LIMIT 1",
            (user_id, canonical),
        ).fetchone()
        if row:
            return _sqlite_row_to_dict(row)
        # Fallback for legacy rows
        row = conn.execute(
            "SELECT * FROM ProductMemory WHERE userId = ? AND LOWER(productName) = LOWER(?) LIMIT 1",
            (user_id, product_name),
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
    """Delete by canonical key OR exact original name — handles all name variants."""
    canonical = _canonical_product_name(product_name)
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'DELETE FROM "ProductMemory" '
                'WHERE "userId" = %s AND ("canonicalName" = %s OR "productName" = %s)',
                (user_id, canonical, product_name),
            )
            return cur.rowcount > 0
    else:
        conn = _sqlite_connect()
        cur = conn.execute(
            "DELETE FROM ProductMemory WHERE userId = ? AND (canonicalName = ? OR productName = ?)",
            (user_id, canonical, product_name),
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


# ---------------------------------------------------------------------------
# ShareToken CRUD
# ---------------------------------------------------------------------------

def create_share_token(token: str, search_id: str, expires_at: Optional[str] = None) -> None:
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'INSERT INTO "ShareToken" (token, search_id, created_at, expires_at) '
                'VALUES (%s, %s, now(), %s) ON CONFLICT (token) DO NOTHING',
                (token, search_id, expires_at),
            )
    else:
        conn = _sqlite_connect()
        conn.execute(
            "INSERT OR IGNORE INTO ShareToken (token, search_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, search_id, _now_iso(), expires_at),
        )
        conn.commit()


def resolve_share_token(token: str) -> Optional[str]:
    """Return the search_id for a token, or None if not found / expired."""
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'SELECT search_id, expires_at FROM "ShareToken" WHERE token = %s',
                (token,),
            )
            row = _pg_fetchone_as_dict(cur)
    else:
        conn = _sqlite_connect()
        row = conn.execute(
            "SELECT search_id, expires_at FROM ShareToken WHERE token = ?",
            (token,),
        ).fetchone()
        row = _sqlite_row_to_dict(row) if row else None

    if not row:
        return None
    expires = row.get("expires_at")
    if expires:
        from datetime import datetime, timezone
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                return None  # expired
        except Exception:
            pass
    return row.get("search_id")


# ---------------------------------------------------------------------------
# EmbeddingCache CRUD
# ---------------------------------------------------------------------------

def get_cached_embedding(hash_key: str) -> Optional[list]:
    """Return cached embedding vector if present and not expired, else None."""
    if _use_postgres():
        with _pg_transaction() as cur:
            cur.execute(
                'SELECT embedding FROM "EmbeddingCache" WHERE hash = %s AND expires_at > now()',
                (hash_key,),
            )
            row = _pg_fetchone_as_dict(cur)
    else:
        conn = _sqlite_connect()
        row = conn.execute(
            "SELECT embedding FROM EmbeddingCache WHERE hash = ? AND expires_at > datetime('now')",
            (hash_key,),
        ).fetchone()
        row = _sqlite_row_to_dict(row) if row else None

    if not row:
        return None
    raw = row.get("embedding")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return raw


def set_cached_embedding(hash_key: str, text: str, provider: str, vec: list) -> None:
    """Persist an embedding vector with TTL. Silently skips on error (non-critical cache)."""
    vec_json = json.dumps(vec)
    dims = len(vec)
    safe_text = text[:500]

    try:
        if _use_postgres():
            with _pg_transaction() as cur:
                cur.execute(
                    """INSERT INTO "EmbeddingCache" (hash, text, provider, embedding, dims)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (hash) DO NOTHING""",
                    (hash_key, safe_text, provider, vec_json, dims),
                )
        else:
            conn = _sqlite_connect()
            conn.execute(
                "INSERT OR IGNORE INTO EmbeddingCache (hash, text, provider, embedding, dims) VALUES (?,?,?,?,?)",
                (hash_key, safe_text, provider, vec_json, dims),
            )
            conn.commit()
    except Exception as exc:
        _logger.debug("[db] EmbeddingCache write failed (non-fatal): %s", exc)

    _maybe_evict_embedding_cache()


def _maybe_evict_embedding_cache() -> None:
    """LRU eviction: if table exceeds 1M rows, delete oldest 10% to cap growth."""
    try:
        if _use_postgres():
            with _pg_transaction() as cur:
                cur.execute('SELECT COUNT(*) FROM "EmbeddingCache"')
                row = cur.fetchone()
                cnt = row[0] if row else 0
                if cnt > 1_000_000:
                    cur.execute(
                        """DELETE FROM "EmbeddingCache" WHERE hash IN (
                               SELECT hash FROM "EmbeddingCache" ORDER BY created_at ASC LIMIT 100000
                           )"""
                    )
        else:
            conn = _sqlite_connect()
            row = conn.execute("SELECT COUNT(*) FROM EmbeddingCache").fetchone()
            cnt = row[0] if row else 0
            if cnt > 1_000_000:
                conn.execute(
                    "DELETE FROM EmbeddingCache WHERE hash IN "
                    "(SELECT hash FROM EmbeddingCache ORDER BY created_at ASC LIMIT 100000)"
                )
                conn.commit()
    except Exception as exc:
        _logger.debug("[db] EmbeddingCache eviction failed (non-fatal): %s", exc)


def purge_expired_embeddings() -> int:
    """Delete expired embedding cache rows. Returns count deleted."""
    try:
        if _use_postgres():
            with _pg_transaction() as cur:
                cur.execute('DELETE FROM "EmbeddingCache" WHERE expires_at < now()')
                return cur.rowcount or 0
        else:
            conn = _sqlite_connect()
            cur = conn.execute("DELETE FROM EmbeddingCache WHERE expires_at < datetime('now')")
            conn.commit()
            return cur.rowcount or 0
    except Exception as exc:
        _logger.warning("[db] EmbeddingCache purge failed: %s", exc)
        return 0


def reassign_user_data(from_user_id: str, to_user_id: str) -> dict[str, int]:
    """
    Migrate all data from one user ID to another (used by adopt-legacy flow).
    Returns count of rows moved per table.
    """
    tables = ["UserSignal", "ProductMemory"]
    counts: dict[str, int] = {}
    try:
        if _use_postgres():
            with _pg_transaction() as cur:
                for table in tables:
                    cur.execute(
                        f'UPDATE "{table}" SET user_id = %s WHERE user_id = %s',
                        (to_user_id, from_user_id),
                    )
                    counts[table] = cur.rowcount or 0
        else:
            conn = _sqlite_connect()
            for table in tables:
                cur = conn.execute(
                    f"UPDATE {table} SET user_id = ? WHERE user_id = ?",
                    (to_user_id, from_user_id),
                )
                counts[table] = cur.rowcount or 0
            conn.commit()
    except Exception as exc:
        _logger.warning("[db] reassign_user_data failed: %s", exc)
    return counts
