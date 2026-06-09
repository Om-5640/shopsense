"""Add userId columns to Search and Profile tables for multi-user auth.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06

Uses 'default' as server_default so pre-auth rows are treated as the
shared guest session.  Users can reclaim old data post-login via
POST /api/auth/adopt-legacy.

SQLite note: render_as_batch=True in env.py activates batch mode, which copies the
table to add the column — required because SQLite does not support transactional DDL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Search table ──────────────────────────────────────────────────────────
    with op.batch_alter_table("Search") as batch_op:
        batch_op.add_column(
            sa.Column("userId", sa.Text, server_default="default", nullable=False)
        )
    op.create_index("ix_search_user_id", "Search", ["userId"])

    # ── Profile table ─────────────────────────────────────────────────────────
    with op.batch_alter_table("Profile") as batch_op:
        batch_op.add_column(
            sa.Column("userId", sa.Text, server_default="default", nullable=False)
        )
    op.create_index("ix_profile_user_id", "Profile", ["userId"])


def downgrade() -> None:
    op.drop_index("ix_search_user_id", table_name="Search")
    with op.batch_alter_table("Search") as batch_op:
        batch_op.drop_column("userId")

    op.drop_index("ix_profile_user_id", table_name="Profile")
    with op.batch_alter_table("Profile") as batch_op:
        batch_op.drop_column("userId")
