"""FastAPI app: every route from PRD Output 2 + health, vaults, documents, jobs status.

Wiring: ``create_app(services)`` takes an ``AppServices`` bundle of port implementations.
Any route whose port is not wired yet returns 501. ``uvicorn atlas.http.app:app``.
All routes accept an optional ``vault`` query param (default: the seeded default vault).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from atlas.http import routes_ingest, routes_links, routes_read, routes_system
from atlas.http.routes_common import UploadConfig
from atlas.ports import GraphService, JobQueue, LinkFeedbackRepository, SearchService, VaultScanner
from atlas.read.protocols import ContentHashLookup, DocumentReader, HealthCheck, JobsStatusReader, VaultReader

API_VERSION = "0.1.0"


@dataclass(frozen=True)
class AppServices:
    """Port implementations the routes call. None = not wired yet (route returns 501)."""

    queue: JobQueue | None = None
    scanner: VaultScanner | None = None
    search: SearchService | None = None
    graph: GraphService | None = None
    feedback: LinkFeedbackRepository | None = None
    documents: DocumentReader | None = None  # GET /api/documents/{id}; also 404s feedback on unknown docs
    jobs: JobsStatusReader | None = None  # GET /api/jobs/status
    vaults: VaultReader | None = None  # GET /api/vaults; also 404s unknown vaults on writes
    health: HealthCheck | None = None  # GET /api/health
    hashes: ContentHashLookup | None = None  # upload "unchanged" flag (DocumentRepository fits)
    uploads: UploadConfig | None = None  # uploads root + per-file size cap


def create_app(services: AppServices | None = None) -> FastAPI:
    app = FastAPI(title="Atlas API", version=API_VERSION, openapi_url="/api/openapi.json", docs_url="/api/docs")
    app.state.services = services or AppServices()
    # Route implementations live in routes_*.py; ports reach them through the FastAPI
    # dependencies in routes_common (overridable via app.dependency_overrides).
    for router in (routes_system.router, routes_ingest.router, routes_read.router, routes_links.router):
        app.include_router(router)
    return app


app = create_app()
