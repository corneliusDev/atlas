"""Composition root for the api process: real Postgres + Ollama adapters behind ``create_app``.

    uvicorn --factory atlas.http.composition:create_production_app

``atlas.http.app:app`` stays unwired (every route 501s) so the OpenAPI export and route tests
need no database. The api never calls the language model: it only enqueues jobs and reads.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

import httpx
from fastapi import FastAPI

from atlas.config import Settings, get_settings
from atlas.http.app import API_VERSION, AppServices, create_app
from atlas.models import build_embedding_model
from atlas.models.ollama import EmbeddingPurpose
from atlas.read.db import connect_factory
from atlas.read.wiring import build_read_services
from atlas.types import DEFAULT_VAULT_ID
from atlas.worker import FsVaultScanner

log = logging.getLogger("atlas.api")


def ollama_probe(settings: Settings, ttl_s: float = 10.0) -> Callable[[], bool]:
    """Cheap "is the embedding model pulled?" check, cached for ``ttl_s``. Never raises."""
    lock = threading.Lock()
    state: dict[str, float | bool] = {"at": 0.0, "ok": False}

    def probe() -> bool:
        with lock:
            if time.monotonic() - float(state["at"]) < ttl_s:
                return bool(state["ok"])
        try:
            resp = httpx.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=2.0)
            names = {m.get("name", "").split(":")[0] for m in resp.json().get("models", [])}
            ok = resp.status_code == 200 and settings.embedding_model.split(":")[0] in names
        except Exception:
            ok = False
        with lock:
            state.update(at=time.monotonic(), ok=ok)
        return ok

    return probe


def create_production_app(settings: Settings | None = None) -> FastAPI:
    from atlas.store import PgDocumentRepository, PgJobQueue, open_pool
    from atlas.store.feedback import PgLinkFeedbackRepository

    settings = settings or get_settings()
    pool = open_pool(settings.database_url, max_size=10)
    documents = PgDocumentRepository(pool)
    queue = PgJobQueue(pool, max_attempts=settings.job_max_attempts)
    read = build_read_services(
        settings,
        connect_factory(settings.database_url),
        build_embedding_model(settings, EmbeddingPurpose.QUERY),
        ollama_probe(settings),
        version=API_VERSION,
    )
    services = AppServices(
        queue=queue,
        scanner=FsVaultScanner(
            queue=queue, documents=documents, roots={DEFAULT_VAULT_ID: settings.vault_root},
            max_file_bytes=settings.max_file_bytes,
        ),
        feedback=PgLinkFeedbackRepository(pool),
        hashes=documents,
        **read.as_kwargs(),
    )
    app = create_app(services)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            pool.close()

    app.router.lifespan_context = lifespan
    return app
