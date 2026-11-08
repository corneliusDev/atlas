"""Fixtures for the Postgres store tests.

Set ATLAS_TEST_DATABASE_URL (or DATABASE_URL) to any Postgres 16 + pgvector server, e.g.

    docker run -d --name atlas-track-d-db -e POSTGRES_USER=atlas -e POSTGRES_PASSWORD=atlas \\
        -p 55434:5432 pgvector/pgvector:pg16
    ATLAS_TEST_DATABASE_URL=postgresql://atlas:atlas@localhost:55434/atlas pytest tests/store

The tests never touch that database's tables: they create a throwaway database on the same
server, migrate it, and drop it at the end of the session.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool

from atlas.store import open_pool
from atlas.store.migrate import migrate

BASE_URL = os.environ.get("ATLAS_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = os.path.dirname(__file__)
    for item in items:
        if str(item.path).startswith(here):
            item.add_marker(pytest.mark.db)
            if not BASE_URL:
                item.add_marker(pytest.mark.skip(reason="ATLAS_TEST_DATABASE_URL / DATABASE_URL not set"))


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    assert BASE_URL
    name = f"atlas_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(BASE_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(BASE_URL)
    params["dbname"] = name
    url = make_conninfo(**{k: str(v) for k, v in params.items() if v is not None})
    try:
        yield url
    finally:
        with psycopg.connect(BASE_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def pool(database_url: str) -> Iterator[ConnectionPool]:
    applied = migrate(database_url)
    assert applied, "a fresh database should get migrations"
    assert migrate(database_url) == []  # idempotent
    p = open_pool(database_url, min_size=1, max_size=12)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture(autouse=True)
def clean(pool: ConnectionPool) -> Iterator[None]:
    with pool.connection() as conn:
        conn.execute(
            "TRUNCATE jobs, link_feedback, semantic_links, wiki_links, document_topics, topics,"
            " chunks, documents, clusters CASCADE"
        )
        conn.execute("DELETE FROM vaults WHERE id <> '00000000-0000-0000-0000-000000000001'")
    yield
