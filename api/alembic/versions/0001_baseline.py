"""Baseline — marks current schema as known. No-op upgrade/downgrade.

Revision ID: 0001
Revises:
Create Date: 2026-06-06

All tables (Search, Profile, UserSignal, ProductMemory, ShareToken, _SchemaVersion)
already exist from api/db.py's _SQLITE_SCHEMA / _PG_SCHEMA inline DDL.
This migration is a no-op that establishes the Alembic version trail.
"""

from typing import Sequence, Union

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
