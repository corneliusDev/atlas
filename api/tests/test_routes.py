"""Track E HTTP routes over fakes (FastAPI TestClient; no Docker)."""

from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atlas.http.app import AppServices, create_app
from atlas.http.dto import DocumentDetail, HealthResponse, JobsStatusResponse, VaultDto
from atlas.http.routes_common import UploadConfig, get_search_service
from atlas.testing.fakes import InMemoryJobQueue, InMemoryLinkFeedbackRepository
from atlas.types import (
    DEFAULT_VAULT_ID,
    ContentHash,
    Depth,
    DocumentId,
    DocumentNode,
    DocumentPair,
    GraphFilters,
    GraphNode,
    GraphStats,
    GraphView,
    JobState,
    LinkEndpoint,
    LinkEvidenceView,
    LinkVerdict,
    NodeKind,
    NodeRef,
    Recluster,
    ScanReport,
    SearchHit,
    SearchQuery,
    Upsert,
    VaultId,
    VaultPath,
    node_key,
)

V = DEFAULT_VAULT_ID
D1, D2 = sorted([DocumentId(uuid.uuid4()), DocumentId(uuid.uuid4())])
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
EMPTY_STATS = GraphStats(documents=0, topics=0, clusters=0, links=0)


# ---- fakes ----------------------------------------------------------------------------------
@dataclass
class FakeSearch:
    calls: list[tuple[VaultId, SearchQuery]] = field(default_factory=list)

    def search(self, vault: VaultId, query: SearchQuery) -> list[SearchHit]:
        self.calls.append((vault, query))
        return [
            SearchHit(
                node=DocumentNode(id=D1), document_id=D1, path=VaultPath("a.md"), title="A", chunk_id=None,
                heading_path=(), snippet="<mark>churn</mark>", score=0.03, keyword_rank=1, semantic_rank=None,
                cluster_id=None,
            )
        ]


@dataclass
class FakeGraph:
    known: set[str] = field(default_factory=set)
    links: dict[DocumentPair, LinkEvidenceView] = field(default_factory=dict)
    global_calls: list[GraphFilters] = field(default_factory=list)
    local_calls: list[tuple[NodeRef, Depth]] = field(default_factory=list)

    def global_graph(self, vault: VaultId, filters: GraphFilters) -> GraphView:
        self.global_calls.append(filters)
        return GraphView(nodes=(), edges=(), clusters=(), stats=EMPTY_STATS)

    def local_graph(self, vault: VaultId, center: NodeRef, depth: Depth) -> GraphView:
        self.local_calls.append((center, depth))
        key = node_key(center)
        nodes = (GraphNode(key=key, ref=center, label="x"),) if key in self.known else ()
        return GraphView(nodes=nodes, edges=(), clusters=(), stats=EMPTY_STATS, center=key)

    def link_evidence(self, vault: VaultId, pair: DocumentPair) -> LinkEvidenceView | None:
        return self.links.get(pair)


@dataclass
class FakeDocuments:
    docs: dict[DocumentId, DocumentDetail] = field(default_factory=dict)
    present: set[DocumentId] = field(default_factory=set)

    def document(self, vault: VaultId, document_id: DocumentId) -> DocumentDetail | None:
        return self.docs.get(document_id)

    def exists(self, vault: VaultId, document_id: DocumentId) -> bool:
        return document_id in self.present or document_id in self.docs


@dataclass
class FakeVaults:
    ids: set[VaultId] = field(default_factory=lambda: {V})

    def vaults(self) -> list[VaultDto]:
        return [VaultDto(id=v, name="Default vault", root_path="/vault", mounted=True, document_count=3) for v in self.ids]

    def exists(self, vault: VaultId) -> bool:
        return vault in self.ids


@dataclass
class FakeHashes:
    stored: dict[tuple[VaultId, VaultPath], ContentHash] = field(default_factory=dict)

    def current_hash(self, vault: VaultId, path: VaultPath) -> ContentHash | None:
        return self.stored.get((vault, path))


class FakeScanner:
    def scan(self, vault: VaultId) -> ScanReport:
        return ScanReport(vault=vault, scanned=3, upserts=2, removes=0, unchanged=1, ignored=())


class FakeJobs:
    def status(self, vault: VaultId, limit: int) -> JobsStatusResponse:
        return JobsStatusResponse(
            vault=vault, counts={s: 0 for s in JobState}, files=[], recent_failures=[], recluster_pending=False, idle=True,
            avg_seconds_per_file=None,
        )


class FakeHealth:
    def check(self) -> HealthResponse:
        return HealthResponse(status="ok", database=True, embeddings=True, llm="enabled", llm_model="claude-opus-5-5",
                              version="0.1.0")


@dataclass
class World:
    client: TestClient
    queue: InMemoryJobQueue
    search: FakeSearch
    graph: FakeGraph
    feedback: InMemoryLinkFeedbackRepository
    documents: FakeDocuments
    hashes: FakeHashes
    uploads: Path


@pytest.fixture()
def world(tmp_path: Path) -> World:
    w = World(
        client=None,  # type: ignore[arg-type]
        queue=InMemoryJobQueue(),
        search=FakeSearch(),
        graph=FakeGraph(),
        feedback=InMemoryLinkFeedbackRepository(),
        documents=FakeDocuments(),
        hashes=FakeHashes(),
        uploads=tmp_path / "uploads",
    )
    services = AppServices(
        queue=w.queue,
        scanner=FakeScanner(),
        search=w.search,
        graph=w.graph,
        feedback=w.feedback,
        documents=w.documents,
        jobs=FakeJobs(),
        vaults=FakeVaults(),
        health=FakeHealth(),
        hashes=w.hashes,
        uploads=UploadConfig(root=w.uploads, max_file_bytes=1024),
    )
    w.client = TestClient(create_app(services))
    return w


def _upload(client: TestClient, files: list[tuple[str, bytes]], **data: Any) -> Any:
    return client.post("/api/uploads", files=[("files", (n, b)) for n, b in files], data=data)


# ---- uploads -------------------------------------------------------------------------------
def test_upload_markdown_writes_file_and_enqueues(world: World) -> None:
    r = _upload(world.client, [("notes/idea.md", b"# Idea\n"), ("pic.png", b"\x89PNG"), ("readme.txt", b"x")])
    assert r.status_code == 200, r.text
    body = r.json()
    assert [a["path"] for a in body["accepted"]] == ["notes/idea.md"]
    assert body["accepted"][0]["unchanged"] is False
    assert {(i["path"], i["reason"]) for i in body["ignored"]} == {("pic.png", "not_markdown"), ("readme.txt", "not_markdown")}
    assert (world.uploads / str(V) / "notes" / "idea.md").read_bytes() == b"# Idea\n"
    [row] = world.queue.rows
    assert row.job == Upsert(vault=V, path=VaultPath("notes/idea.md"), origin="upload")
    assert str(row.id) == body["accepted"][0]["job_id"]


def test_upload_rejects_large_and_invalid_paths(world: World) -> None:
    r = _upload(world.client, [("big.md", b"x" * 1025), (".obsidian/x.md", b"x"), ("../escape.md", b"x"), ("ok.markdown", b"x")])
    body = r.json()
    assert [a["path"] for a in body["accepted"]] == ["ok.markdown"]
    assert {(i["path"], i["reason"]) for i in body["ignored"]} == {
        ("big.md", "too_large"), (".obsidian/x.md", "invalid_path"), ("../escape.md", "invalid_path")
    }
    assert not (world.uploads.parent / "escape.md").exists()


def test_upload_zip_keeps_folders(world: World) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vault/", "")
        zf.writestr("vault/a.md", "# A")
        zf.writestr("vault/sub/b.MD", "# B")
        zf.writestr("vault/img.png", "png")
        zf.writestr("__MACOSX/vault/._a.md", "junk")
        zf.writestr("vault/huge.md", "y" * 2000)
    r = _upload(world.client, [("export.zip", buf.getvalue())])
    body = r.json()
    assert sorted(a["path"] for a in body["accepted"]) == ["vault/a.md", "vault/sub/b.MD"]
    assert {(i["path"], i["reason"]) for i in body["ignored"]} == {("vault/img.png", "not_markdown"), ("vault/huge.md", "too_large")}
    assert (world.uploads / str(V) / "vault" / "sub" / "b.MD").read_text() == "# B"
    assert len(world.queue.rows) == 2


def test_upload_bad_zip_is_ignored(world: World) -> None:
    body = _upload(world.client, [("broken.zip", b"not a zip")]).json()
    assert body["accepted"] == [] and body["ignored"] == [{"path": "broken.zip", "reason": "invalid_path"}]


def test_upload_unchanged_flag_and_replaces_pending_job(world: World) -> None:
    data = b"# Same\n"
    world.hashes.stored[(V, VaultPath("same.md"))] = ContentHash(hashlib.sha256(data).hexdigest())
    first = _upload(world.client, [("same.md", data)]).json()
    assert first["accepted"][0]["unchanged"] is True
    second = _upload(world.client, [("same.md", b"# Changed\n")]).json()
    assert second["accepted"][0]["unchanged"] is False
    assert second["accepted"][0]["job_id"] == first["accepted"][0]["job_id"]  # one pending per path
    assert (world.uploads / str(V) / "same.md").read_bytes() == b"# Changed\n"


def test_upload_unknown_vault_404(world: World) -> None:
    r = _upload(world.client, [("a.md", b"x")], vault=str(uuid.uuid4()))
    assert r.status_code == 404
    assert world.queue.rows == []


def test_upload_needs_uploads_config(tmp_path: Path) -> None:
    c = TestClient(create_app(AppServices(queue=InMemoryJobQueue())))
    assert _upload(c, [("a.md", b"x")]).status_code == 501


# ---- scan / recluster / jobs ------------------------------------------------------------------
def test_scan_and_recluster(world: World) -> None:
    r = world.client.post(f"/api/vaults/{V}/scan")
    assert r.status_code == 200 and r.json()["upserts"] == 2
    assert world.client.post(f"/api/vaults/{uuid.uuid4()}/scan").status_code == 404

    a = world.client.post(f"/api/vaults/{V}/recluster").json()
    b = world.client.post(f"/api/vaults/{V}/recluster").json()
    assert a["job_id"] == b["job_id"] and a["vault"] == str(V)
    assert [row.job for row in world.queue.rows] == [Recluster(vault=V)]
    assert world.client.post(f"/api/vaults/{uuid.uuid4()}/recluster").status_code == 404


def test_jobs_status_health_vaults(world: World) -> None:
    r = world.client.get("/api/jobs/status", params={"limit": 5})
    assert r.status_code == 200 and r.json()["idle"] is True
    assert world.client.get("/api/jobs/status", params={"limit": 0}).status_code == 422
    assert world.client.get("/api/health").json()["status"] == "ok"
    assert world.client.get("/api/vaults").json()["vaults"][0]["id"] == str(V)


# ---- search ---------------------------------------------------------------------------------
def test_search_builds_query(world: World) -> None:
    c = uuid.uuid4()
    r = world.client.get("/api/search", params=[("q", "  churn "), ("tag", "#Product"), ("cluster", str(c)), ("limit", "5")])
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "churn" and body["hits"][0]["document_id"] == str(D1) and body["took_ms"] >= 0
    vault, q = world.search.calls[0]
    assert vault == V and q.text == "churn" and q.limit == 5
    assert q.tags == frozenset({"product"}) and q.cluster_ids == frozenset({c})
    assert world.client.get("/api/search", params={"q": "   "}).status_code == 400
    assert world.client.get("/api/search").status_code == 422


def test_dependency_override_swaps_port() -> None:
    fake = FakeSearch()
    app = create_app()
    app.dependency_overrides[get_search_service] = lambda: fake
    r = TestClient(app).get("/api/search", params={"q": "x"})
    assert r.status_code == 200 and len(fake.calls) == 1


# ---- graph ----------------------------------------------------------------------------------
def test_global_graph_filters(world: World) -> None:
    c = uuid.uuid4()
    r = world.client.get(
        "/api/graph",
        params=[("layer", "document"), ("layer", "ghost"), ("tag", "Travel"), ("cluster", str(c)), ("origin", "upload"),
                ("min_score", "0.6"), ("indexed_after", "2026-11-01T00:00:00Z"), ("include_hidden", "true")],
    )
    assert r.status_code == 200
    f = world.graph.global_calls[0]
    assert f.layers == frozenset({NodeKind.DOCUMENT, NodeKind.GHOST})
    assert f.tags == frozenset({"travel"}) and f.cluster_ids == frozenset({c}) and f.origins == frozenset({"upload"})
    assert f.min_score == 0.6 and f.include_hidden and f.indexed_after == datetime(2026, 11, 1, tzinfo=UTC)
    world.client.get("/api/graph")
    assert world.graph.global_calls[1] == GraphFilters()
    assert world.client.get("/api/graph", params={"min_score": "2"}).status_code == 422


def test_local_graph(world: World) -> None:
    world.graph.known.add(f"doc:{D1}")
    r = world.client.get(f"/api/graph/local/doc:{D1}", params={"depth": 3})
    assert r.status_code == 200 and r.json()["center"] == f"doc:{D1}"
    assert world.graph.local_calls[-1] == (DocumentNode(id=D1), 3)
    assert world.client.get(f"/api/graph/local/doc:{D2}").status_code == 404
    assert world.client.get("/api/graph/local/ghost:Kyoto Ryokan List").status_code == 404
    assert world.client.get("/api/graph/local/nope:1").status_code == 400
    assert world.client.get(f"/api/graph/local/doc:{D1}", params={"depth": 4}).status_code == 422


# ---- links ----------------------------------------------------------------------------------
def _evidence(pair: DocumentPair) -> LinkEvidenceView:
    return LinkEvidenceView(
        pair=pair,
        a=LinkEndpoint(document_id=pair.a, path=VaultPath("a.md"), title="A"),
        b=LinkEndpoint(document_id=pair.b, path=VaultPath("b.md"), title="B"),
        origin="semantic", score=0.8, reason="Both about churn.", a_passage=None, b_passage=None, feedback=None,
    )


def test_link_evidence_either_order(world: World) -> None:
    pair = DocumentPair.of(D1, D2)
    world.graph.links[pair] = _evidence(pair)
    for a, b in ((D1, D2), (D2, D1)):
        r = world.client.get(f"/api/links/{a}/{b}")
        assert r.status_code == 200 and r.json()["pair"] == {"a": str(D1), "b": str(D2)}
    other = DocumentId(uuid.uuid4())
    assert world.client.get(f"/api/links/{D1}/{other}").status_code == 404
    assert world.client.get(f"/api/links/{D1}/{D1}").status_code == 400


def test_feedback_records_ordered_pair(world: World) -> None:
    world.documents.present |= {D1, D2}
    r = world.client.put(f"/api/links/{D2}/{D1}/feedback", json={"verdict": "hidden"})
    assert r.status_code == 200
    assert r.json()["pair"] == {"a": str(D1), "b": str(D2)} and r.json()["verdict"] == "hidden"
    assert world.feedback.verdicts == {(V, DocumentPair.of(D1, D2)): LinkVerdict.HIDDEN}
    world.client.put(f"/api/links/{D1}/{D2}/feedback", json={"verdict": "added"})
    assert world.feedback.verdicts[(V, DocumentPair.of(D1, D2))] is LinkVerdict.ADDED  # PUT replaces
    assert world.client.put(f"/api/links/{D1}/{D2}/feedback", json={"verdict": "maybe"}).status_code == 422
    missing = DocumentId(uuid.uuid4())
    assert world.client.put(f"/api/links/{D1}/{missing}/feedback", json={"verdict": "added"}).status_code == 404


# ---- documents ------------------------------------------------------------------------------
def test_document_view(world: World) -> None:
    detail = DocumentDetail(
        id=D1, vault=V, path=VaultPath("a.md"), origin="vault", title="A", markdown="# A", frontmatter={"k": 1},
        summary="S.", tags=["x"], cluster_id=None, indexed_at=NOW, topics=[], related=[], backlinks=[], outgoing=[],
    )
    world.documents.docs[D1] = detail
    r = world.client.get(f"/api/documents/{D1}")
    assert r.status_code == 200 and r.json()["markdown"] == "# A"
    assert world.client.get(f"/api/documents/{D2}").status_code == 404
    assert world.client.get("/api/documents/not-a-uuid").status_code == 422


def test_unwired_routes_501() -> None:
    c = TestClient(create_app())
    assert c.get(f"/api/documents/{D1}").status_code == 501
    assert c.get("/api/vaults").status_code == 501
    assert c.get("/api/jobs/status").status_code == 501
