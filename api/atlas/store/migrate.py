"""Tiny raw-SQL migration runner: `python -m atlas.store.migrate`.

Applies atlas/store/migrations/NNNN_*.sql in filename order, each in its own transaction,
recording applied files in schema_migrations. Safe to run concurrently (advisory lock) and
repeatedly (already-applied files are skipped). Chosen over Alembic for speed/reliability.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_KEY = 0x41544C4153  # "ATLAS"


def migrate(database_url: str) -> list[str]:
    applied_now: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
            for f in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
                if f.name in done:
                    continue
                with conn.transaction():
                    conn.execute(f.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
                applied_now.append(f.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return applied_now


def main() -> None:
    from atlas.config import get_settings

    url = sys.argv[1] if len(sys.argv) > 1 else get_settings().database_url
    for name in migrate(url):
        print(f"applied {name}")


if __name__ == "__main__":
    main()
