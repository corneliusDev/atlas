"""Read routes: search (SR-1), global / local graph (GR-1..5), link evidence (SL-2), document
view (DV-1/2). Pure translation between HTTP and the read ports; no business rules here."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from atlas.http.dto import DocumentDetail, GraphResponse, LinkEvidenceResponse, SearchResponse
from atlas.http.routes_common import (
    ERR,
    VaultParam,
    get_document_reader,
    get_graph_service,
    get_search_service,
    need,
    parse_pair,
)
from atlas.ports import GraphService, SearchService
from atlas.read.protocols import DocumentReader
from atlas.types import (
    DEFAULT_VAULT_ID,
    ClusterId,
    Depth,
    DocumentId,
    GraphFilters,
    NodeKind,
    SearchQuery,
    VaultId,
    parse_node_key,
)

router = APIRouter()


@router.get("/api/search", response_model=SearchResponse, responses=ERR, tags=["read"])
def search(
    q: Annotated[str, Query(min_length=1, max_length=500)],
    service: Annotated[SearchService | None, Depends(get_search_service)],
    vault: VaultParam = DEFAULT_VAULT_ID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    tag: Annotated[list[str] | None, Query()] = None,
    cluster: Annotated[list[UUID] | None, Query()] = None,
) -> SearchResponse:
    text = q.strip()
    if not text:
        raise HTTPException(status_code=400, detail="query must not be blank")
    svc = need(service, "search")
    query = SearchQuery(
        text=text,
        limit=limit,
        tags=frozenset(t.strip().lower().lstrip("#") for t in tag or () if t.strip()),
        cluster_ids=frozenset(ClusterId(c) for c in cluster or ()),
    )
    t0 = time.monotonic()
    hits = svc.search(VaultId(vault), query)
    return SearchResponse(query=text, hits=hits, took_ms=int((time.monotonic() - t0) * 1000))


@router.get("/api/graph", response_model=GraphResponse, responses=ERR, tags=["read"])
def global_graph(
    service: Annotated[GraphService | None, Depends(get_graph_service)],
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
    svc = need(service, "graph")
    filters = GraphFilters(
        layers=frozenset(layer) if layer else frozenset(NodeKind),
        tags=frozenset(t.strip().lower().lstrip("#") for t in tag or () if t.strip()),
        cluster_ids=frozenset(ClusterId(c) for c in cluster or ()),
        origins=frozenset(origin or ()),
        min_score=min_score,
        indexed_after=indexed_after,
        indexed_before=indexed_before,
        include_hidden=include_hidden,
    )
    return svc.global_graph(VaultId(vault), filters)


@router.get("/api/graph/local/{node}", response_model=GraphResponse, responses=ERR, tags=["read"])
def local_graph(
    node: Annotated[str, Path(description='Node key: "doc:<uuid>", "topic:<uuid>" or "ghost:<name>"')],
    service: Annotated[GraphService | None, Depends(get_graph_service)],
    vault: VaultParam = DEFAULT_VAULT_ID,
    depth: Annotated[int, Query(ge=1, le=3)] = 2,
) -> GraphResponse:
    ref = parse_node_key(node)
    if ref is None:
        raise HTTPException(status_code=400, detail="invalid node key")
    svc = need(service, "local graph")
    d: Depth = 1 if depth == 1 else 2 if depth == 2 else 3
    view = svc.local_graph(VaultId(vault), ref, d)
    if not any(n.key == view.center for n in view.nodes):
        raise HTTPException(status_code=404, detail="node not found")
    return view


@router.get("/api/links/{a}/{b}", response_model=LinkEvidenceResponse, responses=ERR, tags=["read"],
            summary="Why connected? (pair order does not matter)")
def link_evidence(
    a: UUID,
    b: UUID,
    service: Annotated[GraphService | None, Depends(get_graph_service)],
    vault: VaultParam = DEFAULT_VAULT_ID,
) -> LinkEvidenceResponse:
    pair = parse_pair(a, b)
    view = need(service, "link evidence").link_evidence(VaultId(vault), pair)
    if view is None:
        raise HTTPException(status_code=404, detail="no link between these documents")
    return view


@router.get("/api/documents/{document_id}", response_model=DocumentDetail, responses=ERR, tags=["read"])
def document(
    document_id: UUID,
    reader: Annotated[DocumentReader | None, Depends(get_document_reader)],
    vault: VaultParam = DEFAULT_VAULT_ID,
) -> DocumentDetail:
    detail = need(reader, "document view").document(VaultId(vault), DocumentId(document_id))
    if detail is None:
        raise HTTPException(status_code=404, detail="document not found")
    return detail
