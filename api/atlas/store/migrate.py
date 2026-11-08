"""Tiny raw-SQL migration runner: `python -m atlas.store.migrate [url] [--wait SECONDS]`.

The api container runs it before starting uvicorn; ``--wait`` (default 60s) retries the
connection while Postgres is still starting.

Applies atlas/store/migrations/NNNN_*.sql in filename order, each in its own transaction,
recording applied files in schema_migrations. Safe to run concurrently (advisory lock) and
repeatedly (already-applied files are skipped). Chosen over Alembic for speed/reliability.
"""

from __future__ import annotations

import sys
import time
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


def wait_for_database(database_url: str, timeout_s: float = 60.0, interval_s: float = 1.0) -> None:
    """Block until a connection succeeds, or re-raise the last error after ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with psycopg.connect(database_url, connect_timeout=5):
                return
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval_s)


def main(argv: list[str] | None = None) -> None:
    import argparse

    from atlas.config import get_settings

    parser = argparse.ArgumentParser(prog="python -m atlas.store.migrate")
    parser.add_argument("url", nargs="?", default=None, help="database URL (default: DATABASE_URL)")
    parser.add_argument("--wait", type=float, default=60.0, help="seconds to wait for Postgres")
    args = parser.parse_args(argv)
    url = args.url or get_settings().database_url
    wait_for_database(url, args.wait)
    applied = migrate(url)
    for name in applied:
        print(f"applied {name}")
    if not applied:
        print("schema up to date", file=sys.stderr)


if __name__ == "__main__":
    main()
