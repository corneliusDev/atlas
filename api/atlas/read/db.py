"""Connection plumbing shared by the Pg read services.

Services take a ``Connect``: a zero-arg callable returning a context manager that yields a
psycopg connection (``psycopg.connect(url)`` or ``ConnectionPool.connection``). Vectors are
sent as pgvector text literals with an explicit ``::vector`` cast, so no adapter registration
is needed on pooled connections.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row

Connection = psycopg.Connection[Any]
Connect = Callable[[], AbstractContextManager[Connection]]
Row = dict[str, Any]
Params = Mapping[str, Any] | Sequence[Any] | None


def connect_factory(database_url: str) -> Connect:
    """One short-lived autocommit connection per call (fine for a localhost single-user app)."""

    def _connect() -> AbstractContextManager[Connection]:
        return psycopg.connect(database_url, autocommit=True)

    return _connect


def vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in vec) + "]"


def fetch_all(conn: Connection, sql: str, params: Params = None) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_one(conn: Connection, sql: str, params: Params = None) -> Row | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()
