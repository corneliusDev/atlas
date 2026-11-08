"""Connection pool + pgvector helpers shared by every Postgres adapter.

Every connection handed out by ``open_pool`` has the pgvector type registered, so ``vector``
columns read back as numpy arrays and ``to_vector`` values can be passed as parameters.
"""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

import numpy as np
import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from atlas.types import Embedding

# classid for pg_advisory_xact_lock(int, int): "AT"
_VAULT_LOCK_CLASS = 0x4154


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)


def open_pool(database_url: str, *, min_size: int = 1, max_size: int = 10, timeout: float = 30.0) -> ConnectionPool:
    """Open a pool whose connections know the ``vector`` type. Migrations must have run first
    (the extension must exist). Close it with ``pool.close()`` or use it as a context manager."""
    pool = ConnectionPool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        open=False,
        configure=_configure,
        timeout=timeout,
        name="atlas",
    )
    pool.open(wait=True, timeout=timeout)
    return pool


def to_vector(v: Sequence[float]) -> np.ndarray:
    return np.asarray(v, dtype=np.float32)


def from_vector(v: object) -> Embedding:
    """pgvector >= 0.4 reads ``vector`` as ``pgvector.Vector``; older versions as ndarray."""
    if isinstance(v, Vector):
        v = v.to_numpy()
    arr = np.asarray(v, dtype=np.float32)
    return tuple(float(x) for x in arr.tolist())


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def lock_vault(conn: psycopg.Connection, vault: UUID) -> None:
    """Transaction-scoped advisory lock serialising graph writes for one vault
    (save_document, delete_document, replace_clusters). These transactions are short (no model
    calls inside), and the lock removes races on topic merging, orphan-topic cleanup, semantic
    link FKs to concurrently deleted documents, and cluster FKs during a re-cluster."""
    conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (_VAULT_LOCK_CLASS, str(vault)))
