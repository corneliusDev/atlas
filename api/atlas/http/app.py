"""FastAPI app: every route from PRD Output 2 + health, vaults, documents, jobs status.

Wiring: ``create_app(services)`` takes an ``AppServices`` bundle of port implementations.
Any route whose port is not wired yet returns 501. ``uvicorn atlas.http.app:app``.
All routes accept an optional ``vault`` query param (default: the seeded default vault).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Path, Query, Request, UploadFile

from atlas.http.dto import (
    DocumentDetail,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    GraphResponse,
    HealthResponse,
    JobsStatusResponse,
    LinkEvidenceResponse,
    ReclusterResponse,
    ScanResponse,
    SearchResponse,
    UploadResponse,
    VaultListResponse,
)
from atlas.ports import GraphService, JobQueue, LinkFeedbackRepository, SearchService, VaultScanner
from atlas.types import (
    DEFAULT_VAULT_ID,
    ClusterId,
    Depth,
    DocumentId,
    DocumentPair,
    GraphFilters,
    NodeKind,
    VaultId,
    parse_node_key,
)

API_VERSION = "0.1.0"


@dataclass(frozen=True)
class AppServices:
    """Port implementations the routes call. None = not wired yet (route returns 501)."""

    queue: JobQueue | None = None
    scanner: VaultScanner | None = None
    search: SearchService | None = None
    graph: GraphService | None = None
    feedback: LinkFeedbackRepository | None = None


VaultParam = Annotated[UUID, Query(description="Vault id; defaults to the seeded default vault")]

_ERR: dict[int | str, dict[str, Any]] = {400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 501: {"model": ErrorResponse}}


def _not_implemented(what: str) -> NoReturn:
    raise HTTPException(status_code=501, detail=f"{what} not implemented yet")


def _pair(a: UUID, b: UUID) -> DocumentPair:
    if a == b:
        raise HTTPException(status_code=400, detail="a and b must be different documents")
    return DocumentPair.of(DocumentId(a), DocumentId(b))


def create_app(services: AppServices | None = None) -> FastAPI:
    app = FastAPI(title="Atlas API", version=API_VERSION, openapi_url="/api/openapi.json", docs_url="/api/docs")
    app.state.services = services or AppServices()

    def svc(request: Request) -> AppServices:
        s: AppServices = request.app.state.services
        return s

    @app.get("/api/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        _not_implemented("health")

    @app.get("/api/vaults", response_model=VaultListResponse, tags=["vaults"])
    def list_vaults() -> VaultListResponse:
        _not_implemented("list vaults")

    @app.post("/api/uploads", response_model=UploadResponse, responses=_ERR, tags=["ingest"],
              summary="Upload .md/.markdown files or a .zip; one Upsert(origin=upload) job per file")
    def upload(
        request: Request,
        files: Annotated[list[UploadFile], File(description=".md, .markdown or .zip files")],
        vault: Annotated[UUID, Form()] = DEFAULT_VAULT_ID,
    ) -> UploadResponse:
        _not_implemented("upload")

    @app.post("/api/vaults/{vault_id}/scan", response_model=ScanResponse, responses=_ERR, tags=["ingest"])
    def scan(request: Request, vault_id: UUID) -> ScanResponse:
        s = svc(request)
        if s.scanner is None:
            _not_implemented("scan")
        return s.scanner.scan(VaultId(vault_id))

    @app.post("/api/vaults/{vault_id}/recluster", response_model=ReclusterResponse, responses=_ERR, tags=["ingest"])
    def recluster(request: Request, vault_id: UUID) -> ReclusterResponse:
        _not_implemented("recluster")

    @app.get("/api/jobs/status", response_model=JobsStatusResponse, tags=["ingest"],
             summary="Progress tray: counts by state, latest job per file, recent failures")
    def jobs_status(
        request: Request,
        vault: VaultParam = DEFAULT_VAULT_ID,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> JobsStatusResponse:
        _not_implemented("jobs status")

    @app.get("/api/search", response_model=SearchResponse, responses=_ERR, tags=["read"])
    def search(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=500)],
        vault: VaultParam = DEFAULT_VAULT_ID,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        tag: Annotated[list[str] | None, Query()] = None,
        cluster: Annotated[list[UUID] | None, Query()] = None,
    ) -> SearchResponse:
        _not_implemented("search")

    @app.get("/api/graph", response_model=GraphResponse, responses=_ERR, tags=["read"])
    def global_graph(
        request: Request,
        vault: VaultParam = DEFAULT_VAULT_ID,
        layer: Annotated[list[NodeKind] | None, Query(description="Node layers; default all")] = None,
        tag: Annotated[list[str] | None, Query()] = None,
        cluster: Annotated[list[UUID] | None, Query()] = None,
        origin: Annotated[list[Literal["vault", "upload"]] | None, Query()] = None,
        min_score: Annotated[float, Query(ge=0.0, le=1.0)] = 0.0,
        indexed_after: datetime | None = None,
        indexed_before: datetime | None = None,
        include_hidden: bool = False,
    ) -> GraphResponse:
        s = svc(request)
        if s.graph is None:
            _not_implemented("graph")
        filters = GraphFilters(
            layers=frozenset(layer) if layer else frozenset(NodeKind),
            tags=frozenset(tag or ()),
            cluster_ids=frozenset(ClusterId(c) for c in cluster or ()),
            origins=frozenset(origin or ()),
            min_score=min_score,
            indexed_after=indexed_after,
            indexed_before=indexed_before,
            include_hidden=include_hidden,
        )
        return s.graph.global_graph(VaultId(vault), filters)

    @app.get("/api/graph/local/{node}", response_model=GraphResponse, responses=_ERR, tags=["read"])
    def local_graph(
        request: Request,
        node: Annotated[str, Path(description='Node key: "doc:<uuid>", "topic:<uuid>" or "ghost:<name>"')],
        vault: VaultParam = DEFAULT_VAULT_ID,
        depth: Annotated[int, Query(ge=1, le=3)] = 2,
    ) -> GraphResponse:
        ref = parse_node_key(node)
        if ref is None:
            raise HTTPException(status_code=400, detail="invalid node key")
        s = svc(request)
        if s.graph is None:
            _not_implemented("local graph")
        d: Depth = 1 if depth == 1 else 2 if depth == 2 else 3
        return s.graph.local_graph(VaultId(vault), ref, d)

    @app.get("/api/links/{a}/{b}", response_model=LinkEvidenceResponse, responses=_ERR, tags=["read"],
             summary="Why connected? (pair order does not matter)")
    def link_evidence(request: Request, a: UUID, b: UUID, vault: VaultParam = DEFAULT_VAULT_ID) -> LinkEvidenceResponse:
        pair = _pair(a, b)
        s = svc(request)
        if s.graph is None:
            _not_implemented("link evidence")
        view = s.graph.link_evidence(VaultId(vault), pair)
        if view is None:
            raise HTTPException(status_code=404, detail="no link between these documents")
        return view

    @app.put("/api/links/{a}/{b}/feedback", response_model=FeedbackResponse, responses=_ERR, tags=["links"])
    def link_feedback(
        request: Request, a: UUID, b: UUID, body: FeedbackRequest, vault: VaultParam = DEFAULT_VAULT_ID
    ) -> FeedbackResponse:
        _pair(a, b)
        _not_implemented("link feedback")

    @app.get("/api/documents/{document_id}", response_model=DocumentDetail, responses=_ERR, tags=["read"])
    def document(request: Request, document_id: UUID, vault: VaultParam = DEFAULT_VAULT_ID) -> DocumentDetail:
        _not_implemented("document view")

    return app


app = create_app()
