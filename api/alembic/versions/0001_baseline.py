"""Baseline — creates the original schema tables (pre-auth, pre-embedding-cache).

Revision ID: 0001
Revises:
Create Date: 2026-06-06

All CREATE TABLE statements use IF NOT EXISTS so this migration is idempotent
on databases that already have tables (e.g. existing deployments where db.py's
init_db() already ran).  On a fresh database (CI, new developer), this creates
all tables so that migration 0002 can ALTER them.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS Search (
            id             TEXT PRIMARY KEY,
            query          TEXT NOT NULL,
            category       TEXT NOT NULL DEFAULT '',
            region         TEXT NOT NULL DEFAULT 'global',
            status         TEXT NOT NULL DEFAULT 'pending',
            createdAt      TEXT NOT NULL,
            profile        TEXT,
            rubric         TEXT,
            analysis       TEXT,
            scoredProducts TEXT,
            explanations   TEXT,
            shoppingLinks  TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS ShareToken (
            token      TEXT PRIMARY KEY,
            search_id  TEXT NOT NULL REFERENCES Search(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS sharetoken_search_idx ON ShareToken (search_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS Profile (
            category  TEXT PRIMARY KEY,
            data      TEXT NOT NULL,
            updatedAt TEXT NOT NULL
        )
    """)

    op.execute("""
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
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS usersignal_user_idx ON UserSignal (userId, createdAt)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS ProductMemory (
            id           TEXT PRIMARY KEY,
            userId       TEXT NOT NULL DEFAULT 'default',
            productName  TEXT NOT NULL,
            canonicalName TEXT,
            category     TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'considered',
            ourScore     REAL,
            userFeedback TEXT,
            createdAt    TEXT NOT NULL,
            UNIQUE(userId, productName)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS productmemory_canonical_idx "
        "ON ProductMemory (userId, canonicalName)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS _SchemaVersion (
            version   INTEGER PRIMARY KEY,
            appliedAt TEXT NOT NULL
        )
    """)


def downgrade() -> None:
    # Baseline: no downgrade path — cannot go before the beginning of schema history.
    pass
