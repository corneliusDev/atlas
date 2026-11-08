"""GET /api/health: database reachable, embeddings reachable, LLM mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from atlas.http.dto import HealthResponse
from atlas.read.db import Connect, fetch_one


@dataclass
class PgHealthCheck:
    """Implements ``atlas.read.protocols.HealthCheck``.

    ``embeddings_ok`` is a cheap probe supplied by the composition root (e.g. the Ollama
    adapter's "model pulled?" check); it must not raise. ``llm_model`` None = embeddings-only.
    """

    connect: Connect
    embeddings_ok: Callable[[], bool]
    llm_model: str | None
    version: str

    def check(self) -> HealthResponse:
        try:
            with self.connect() as conn:
                db = fetch_one(conn, "SELECT 1 AS ok") is not None
        except Exception:
            db = False
        try:
            emb = bool(self.embeddings_ok())
        except Exception:
            emb = False
        return HealthResponse(
            status="ok" if db and emb else "degraded",
            database=db,
            embeddings=emb,
            llm="enabled" if self.llm_model else "embeddings_only",
            llm_model=self.llm_model,
            version=self.version,
        )
