"""
Alembic migration environment.

Uses raw SQL (no SQLAlchemy ORM) to stay consistent with the existing db.py approach.
Reads database URL from environment:
  - POSTGRES_URL  → used as-is if set
  - otherwise     → SQLite at web/prisma/shopping.db (relative to project root)
"""

import os
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context

# Ensure api/ and project root are importable
_API_DIR = Path(__file__).parent.parent          # api/
_ROOT = _API_DIR.parent                          # project root
for _p in [str(_API_DIR), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
# override=False: real env vars (e.g. CI secrets) take precedence over .env values.
# This is the opposite of the app default — Alembic runs in contexts (CI, shell with
# explicit POSTGRES_URL="") where the caller's intent should not be silently overridden.
load_dotenv(str(_ROOT / ".env"), override=False)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM metadata — all migrations are written as raw SQL
target_metadata = None


def _sqlite_fallback_url() -> str:
    sqlite_path = _ROOT / "web" / "prisma" / "shopping.db"
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{sqlite_path}"


def _get_database_url() -> str:
    # ALEMBIC_DATABASE_URL: explicit override, highest priority.
    explicit = os.environ.get("ALEMBIC_DATABASE_URL", "").strip()
    if explicit:
        return explicit

    pg = os.environ.get("POSTGRES_URL", "").strip()
    if pg:
        # Probe the connection with a short timeout before committing to it.
        # Common on dev machines: POSTGRES_URL is in .env but Postgres isn't running.
        # Falling back to SQLite silently is far better than a cryptic connection error.
        try:
            probe = create_engine(
                pg,
                poolclass=pool.NullPool,
                connect_args={"connect_timeout": 3},
            )
            with probe.connect():
                pass
            probe.dispose()
            return pg
        except Exception:
            import logging
            logging.getLogger("alembic.env").warning(
                "[alembic] POSTGRES_URL is set but unreachable — "
                "falling back to SQLite. Set ALEMBIC_DATABASE_URL to suppress this warning."
            )

    return _sqlite_fallback_url()


def run_migrations_offline() -> None:
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _get_database_url()
    # SQLite: NullPool avoids threading issues with single-file DB
    pool_cls = pool.NullPool if url.startswith("sqlite") else pool.QueuePool
    connectable = create_engine(url, poolclass=pool_cls)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite does not support transactional DDL natively;
            # render_as_batch=True enables Alembic's batch migration mode
            # so column ADD/DROP works on SQLite via table copy.
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
