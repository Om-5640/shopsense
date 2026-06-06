"""
Post-migration report: shows counts of pre-auth legacy rows.

Run after `alembic upgrade head` to understand the scope of legacy data.
Users can reclaim their old data post-login via POST /api/auth/adopt-legacy.

Usage:
    cd api
    python migrate_legacy_users.py
"""

import sys
from pathlib import Path

_API_DIR = Path(__file__).parent
_ROOT = _API_DIR.parent
for _p in [str(_API_DIR), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db import _sqlite_connect, _use_postgres


def report() -> None:
    if _use_postgres():
        print("[migrate] Postgres mode — legacy row counts must be checked manually.")
        print("  SELECT COUNT(*) FROM \"Search\"  WHERE user_id = '__legacy__';")
        print("  SELECT COUNT(*) FROM \"Profile\" WHERE user_id = '__legacy__';")
        return

    conn = _sqlite_connect()
    for table in ["Search", "Profile"]:
        try:
            row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE user_id = '__legacy__'"
            ).fetchone()
            cnt = row[0] if row else 0
            if cnt > 0:
                print(
                    f"[migrate] {cnt} legacy rows in {table} "
                    f"— users can adopt them post-login via POST /api/auth/adopt-legacy"
                )
            else:
                print(f"[migrate] {table}: clean (no legacy rows)")
        except Exception as e:
            print(f"[migrate] {table}: could not query ({e}) — migration may not have run yet")


if __name__ == "__main__":
    report()
