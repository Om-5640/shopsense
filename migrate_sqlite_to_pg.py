"""
One-time migration: copy existing SQLite data (Search + Profile rows) into Postgres.

Run after `docker-compose up -d` and setting POSTGRES_URL in your .env:
  python migrate_sqlite_to_pg.py

Safe to run multiple times — uses INSERT ... ON CONFLICT DO NOTHING.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

POSTGRES_URL = os.environ.get("POSTGRES_URL", "")
if not POSTGRES_URL:
    print("ERROR: POSTGRES_URL is not set in .env. Nothing to migrate.")
    sys.exit(1)

SQLITE_PATH = Path(__file__).parent / "web" / "prisma" / "shopping.db"
if not SQLITE_PATH.exists():
    print(f"SQLite DB not found at {SQLITE_PATH}. Nothing to migrate.")
    sys.exit(0)

try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


def migrate() -> None:
    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cur = pg_conn.cursor()

    # --- Enable pgvector ---
    pg_cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- Create tables in Postgres if they don't exist ---
    from api.db import _PG_SCHEMA  # reuse schema definition
    pg_cur.execute(_PG_SCHEMA)
    pg_conn.commit()

    # --- Migrate Search rows ---
    searches = sqlite_conn.execute("SELECT * FROM Search").fetchall()
    print(f"Migrating {len(searches)} Search rows...")
    for row in searches:
        d = dict(row)
        try:
            pg_cur.execute(
                """INSERT INTO "Search"
                   (id, query, category, region, status, "createdAt",
                    profile, rubric, analysis, "scoredProducts", explanations, "shoppingLinks")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (
                    d["id"], d["query"], d["category"], d["region"], d["status"],
                    d["createdAt"],
                    d.get("profile"), d.get("rubric"), d.get("analysis"),
                    d.get("scoredProducts"), d.get("explanations"), d.get("shoppingLinks"),
                ),
            )
        except Exception as exc:
            print(f"  [WARN] Search {d['id']}: {exc}")
    pg_conn.commit()
    print(f"  Done.")

    # --- Migrate Profile rows ---
    profiles = sqlite_conn.execute("SELECT * FROM Profile").fetchall()
    print(f"Migrating {len(profiles)} Profile rows...")
    for row in profiles:
        d = dict(row)
        try:
            pg_cur.execute(
                """INSERT INTO "Profile" (category, data, "updatedAt")
                   VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (d["category"], d["data"], d["updatedAt"]),
            )
        except Exception as exc:
            print(f"  [WARN] Profile {d['category']}: {exc}")
    pg_conn.commit()
    print(f"  Done.")

    # --- Migrate UserSignal rows (if any) ---
    try:
        signals = sqlite_conn.execute("SELECT * FROM UserSignal").fetchall()
        print(f"Migrating {len(signals)} UserSignal rows...")
        for row in signals:
            d = dict(row)
            try:
                emb_val = None
                if d.get("embedding"):
                    try:
                        emb_list = json.loads(d["embedding"])
                        emb_val = "[" + ",".join(str(x) for x in emb_list) + "]"
                    except Exception:
                        pass
                pg_cur.execute(
                    """INSERT INTO "UserSignal"
                       (id, "userId", "signalType", "productName", category, text,
                        embedding, strength, "sourceSearchId", "createdAt")
                       VALUES (%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (
                        d["id"], d.get("userId", "default"), d["signalType"],
                        d.get("productName"), d.get("category"), d["text"],
                        emb_val, d.get("strength", "moderate"),
                        d.get("sourceSearchId"), d["createdAt"],
                    ),
                )
            except Exception as exc:
                print(f"  [WARN] Signal {d['id']}: {exc}")
        pg_conn.commit()
        print(f"  Done.")
    except sqlite3.OperationalError:
        print("  No UserSignal table in SQLite (v6 DB) — skipping.")

    # --- Migrate ProductMemory rows (if any) ---
    try:
        products = sqlite_conn.execute("SELECT * FROM ProductMemory").fetchall()
        print(f"Migrating {len(products)} ProductMemory rows...")
        for row in products:
            d = dict(row)
            try:
                pg_cur.execute(
                    """INSERT INTO "ProductMemory"
                       (id, "userId", "productName", category, status,
                        "ourScore", "userFeedback", "createdAt")
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (
                        d["id"], d.get("userId", "default"), d["productName"],
                        d["category"], d["status"], d.get("ourScore"),
                        d.get("userFeedback"), d["createdAt"],
                    ),
                )
            except Exception as exc:
                print(f"  [WARN] ProductMemory {d['id']}: {exc}")
        pg_conn.commit()
        print(f"  Done.")
    except sqlite3.OperationalError:
        print("  No ProductMemory table in SQLite — skipping.")

    pg_cur.close()
    pg_conn.close()
    sqlite_conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
