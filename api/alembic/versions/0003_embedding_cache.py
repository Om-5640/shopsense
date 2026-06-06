"""Add EmbeddingCache table for DB-persisted embedding vectors.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-06

Adds a DB-backed tier-2 cache so embeddings survive server restarts.
Tier-1 (in-memory dict in embeddings.py) is still checked first for speed.

TTL: expires_at defaults to 1 year from insert.  A 24h cleanup coroutine in
main.py purges expired rows.  An LRU cap at 1M rows evicts oldest 10% on write.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        expires_default = "NOW() + INTERVAL '1 year'"
    else:
        expires_default = "datetime('now', '+1 year')"

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS EmbeddingCache (
            hash        TEXT PRIMARY KEY,
            text        TEXT NOT NULL,
            provider    TEXT NOT NULL,
            embedding   TEXT NOT NULL,
            dims        INTEGER NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at  TIMESTAMP DEFAULT ({expires_default})
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ec_expires ON EmbeddingCache(expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ec_created ON EmbeddingCache(created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ec_expires")
    op.execute("DROP INDEX IF EXISTS idx_ec_created")
    op.execute("DROP TABLE IF EXISTS EmbeddingCache")
