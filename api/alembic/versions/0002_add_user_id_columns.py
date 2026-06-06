"""Add user_id columns to Search and Profile tables for multi-user auth.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06

Uses '__legacy__' as server_default (not 'guest') so pre-auth rows are clearly
distinguishable from new guest rows.  Users can reclaim old data post-login via
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
            sa.Column("user_id", sa.Text, server_default="__legacy__", nullable=False)
        )
    op.create_index("ix_search_user_id", "Search", ["user_id"])

    # ── Profile table ─────────────────────────────────────────────────────────
    # Profile currently uses category as primary key.  We preserve that PK and
    # add user_id as a regular column.  The save_profile_db / get_profile
    # functions in db.py will be updated to filter by (user_id, category).
    with op.batch_alter_table("Profile") as batch_op:
        batch_op.add_column(
            sa.Column("user_id", sa.Text, server_default="__legacy__", nullable=False)
        )
    op.create_index("ix_profile_user_id", "Profile", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_search_user_id", table_name="Search")
    with op.batch_alter_table("Search") as batch_op:
        batch_op.drop_column("user_id")

    op.drop_index("ix_profile_user_id", table_name="Profile")
    with op.batch_alter_table("Profile") as batch_op:
        batch_op.drop_column("user_id")
