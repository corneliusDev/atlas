"""Wave 0 contract tests: unions round-trip through JSON, fakes satisfy the ports, migration applies."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, assert_never

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from atlas import ports
from atlas.http.app import create_app
from atlas.testing.fakes import (
    FakeEmbeddingModel,
    FakeLanguageModel,
    InMemoryClusterRepository,
    InMemoryDocumentRepository,
    InMemoryJobQueue,
    InMemoryLinkFeedbackRepository,
    cosine,
)
from atlas.types import (
    DEFAULT_VAULT_ID,
    EMBEDDING_DIM,
    ChunkId,
    ClusterId,
    ContentHash,
    DocumentAggregate,
    DocumentId,
    DocumentNode,
    DocumentPair,
    EmbeddedChunk,
    GaveUp,
    GhostNode,
    GraphFilters,
    Indexed,
    IngestError,
    IngestJob,
    IngestOutcome,
    JobState,
    Link,
    ModelTimeout,
    ModelUnavailable,
    NodeKind,
    NodeRef,
    NotUtf8,
    ParsedNote,
    Reclustered,
    Recluster,
    Remove,
    Removed,
    RetryAt,
    RetryDecision,
    Saved,
    SaveResult,
    SemanticLink,
    Skipped,
    SkipReason,
    Superseded,
    TopicId,
    TopicNode,
    Upsert,
    VaultPath,
    WikiLink,
    chunk_id_for,
    document_id_for,
    node_key,
    parse_node_key,
    parse_vault_path,
)

V = DEFAULT_VAULT_ID
P = VaultPath("notes/ideas.md")
D1, D2 = sorted([DocumentId(uuid.uuid4()), DocumentId(uuid.uuid4())])
PAIR = DocumentPair(a=D1, b=D2)
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)

CASES: list[tuple[Any, list[Any]]] = [
    (IngestJob, [Upsert(vault=V, path=P, origin="vault"), Upsert(vault=V, path=P, origin="upload"), Remove(vault=V, path=P), Recluster(vault=V)]),
    (
        IngestOutcome,
        [
            Indexed(document_id=D1, path=P, link_count=3, topic_count=2, cluster_id=None),
            Indexed(document_id=D1, path=P, link_count=0, topic_count=0, cluster_id=ClusterId(uuid.uuid4())),
            Skipped(path=P, reason=SkipReason.UNCHANGED),
            Skipped(path=P, reason=SkipReason.SUPERSEDED),
            Removed(path=P),
            Reclustered(cluster_count=6),
        ],
    ),
    (IngestError, [ModelUnavailable(detail="ollama down"), ModelTimeout(step="embed"), NotUtf8(path=P)]),
    (SaveResult, [Saved(document_id=D1), Superseded(stored_hash=ContentHash("ab" * 32))]),
    (RetryDecision, [RetryAt(at=NOW, attempt=2), GaveUp(attempts=3)]),
    (
        Link,
        [
            SemanticLink(pair=PAIR, score=0.81, reason=None, evidence=(ChunkId(uuid.uuid4()), ChunkId(uuid.uuid4()))),
            WikiLink(source=D1, target_name="Pricing Strategy", anchor="Tiers"),
        ],
    ),
    (NodeRef, [DocumentNode(id=D1), TopicNode(id=TopicId(uuid.uuid4())), GhostNode(name="Missing Note")]),
]


@pytest.mark.parametrize(("union", "values"), CASES, ids=[str(i) for i in range(len(CASES))])
def test_unions_round_trip_json(union: Any, values: list[Any]) -> None:
    ta: TypeAdapter[Any] = TypeAdapter(union)
    for v in values:
        js = ta.dump_json(v)
        back = ta.validate_json(js)
        assert back == v and type(back) is type(v), js


def test_discriminator_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(IngestJob).validate_python({"kind": "explode", "vault": str(V)})


def test_frozen() -> None:
    with pytest.raises(ValidationError):
        Removed(path=P).path = VaultPath("x.md")  # type: ignore[misc]


def test_retryable_classvars() -> None:
    assert ModelUnavailable.retryable and ModelTimeout.retryable and not NotUtf8.retryable


def outcome_label(o: Indexed | Skipped | Removed | Reclustered) -> str:
    match o:
        case Indexed():
            return "indexed"
        case Skipped():
            return "skipped"
        case Removed():
            return "removed"
        case Reclustered():
            return "reclustered"
        case _:
            assert_never(o)


def test_exhaustive_match() -> None:
    assert outcome_label(Removed(path=P)) == "removed"


def test_document_pair_ordering() -> None:
    assert DocumentPair.of(D2, D1) == PAIR
    with pytest.raises(ValidationError):
        DocumentPair(a=D2, b=D1)
    with pytest.raises(ValueError):
        DocumentPair.of(D1, D1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("notes/ideas.md", "notes/ideas.md"),
        ("./a/B.MARKDOWN", "a/B.MARKDOWN"),
        ("a\\b.md", "a/b.md"),
        ("img.png", None),
        ("notes.txt", None),
        ("/etc/x.md", None),
        ("../x.md", None),
        (".obsidian/x.md", None),
        ("a//b.md", None),
        (".md", None),
        ("", None),
    ],
)
def test_parse_vault_path(raw: str, expected: str | None) -> None:
    assert parse_vault_path(raw) == expected


def test_node_keys_round_trip() -> None:
    for ref in (DocumentNode(id=D1), TopicNode(id=TopicId(uuid.uuid4())), GhostNode(name="Some: Note")):
        assert parse_node_key(node_key(ref)) == ref
    assert parse_node_key("doc:not-a-uuid") is None
    assert parse_node_key("nope") is None


def test_deterministic_ids() -> None:
    assert document_id_for(V, P) == document_id_for(V, P) != document_id_for(V, VaultPath("other.md"))
    assert chunk_id_for(D1, 0) == chunk_id_for(D1, 0) != chunk_id_for(D1, 1)


def test_graph_filters_defaults() -> None:
    assert GraphFilters().layers == frozenset(NodeKind)
    assert GraphFilters.model_validate_json(GraphFilters(layers=frozenset({NodeKind.DOCUMENT})).model_dump_json()).layers == {NodeKind.DOCUMENT}


# ---- fakes satisfy the ports (static check via assignment; runtime smoke) --------------
def test_fakes_conform_to_ports() -> None:
    _e: ports.EmbeddingModel = FakeEmbeddingModel()
    _l: ports.LanguageModel = FakeLanguageModel()
    _d: ports.DocumentRepository = InMemoryDocumentRepository()
    _c: ports.ClusterRepository = InMemoryClusterRepository()
    _f: ports.LinkFeedbackRepository = InMemoryLinkFeedbackRepository()
    _q: ports.JobQueue = InMemoryJobQueue()


def test_fake_embedding_deterministic() -> None:
    m = FakeEmbeddingModel()
    a, b, c = m.embed(["hello", "hello", "world"])
    assert a == b and len(a) == EMBEDDING_DIM and abs(cosine(a, a) - 1) < 1e-9 and cosine(a, c) < 0.3


def _agg(path: VaultPath, h: str, text: str) -> DocumentAggregate:
    doc = document_id_for(V, path)
    emb = FakeEmbeddingModel().embed([text])[0]
    return DocumentAggregate(
        vault=V, document_id=doc, path=path, origin="vault", content_hash=ContentHash(h), title=path, frontmatter={},
        tags=(), summary=None, doc_embedding=emb,
        chunks=(EmbeddedChunk(id=chunk_id_for(doc, 0), ordinal=0, heading_path=(), text=text, embedding=emb),),
        topics=(), wiki_links=(), semantic_links=(), cluster_id=None, indexed_at=NOW,
    )


def test_in_memory_repo_stale_hash() -> None:
    repo = InMemoryDocumentRepository()
    assert repo.save_document(_agg(P, "h1", "x"), expected_hash=None) == Saved(document_id=document_id_for(V, P))
    assert repo.current_hash(V, P) == "h1"
    assert repo.save_document(_agg(P, "h3", "x"), expected_hash=ContentHash("h0")) == Superseded(stored_hash=ContentHash("h1"))
    repo.save_document(_agg(VaultPath("b.md"), "h2", "y"), expected_hash=None)
    nn = repo.nearest_documents(V, _agg(P, "h", "x").doc_embedding, k=5, exclude=P)
    assert [n.path for n in nn] == ["b.md"] and nn[0].chunks
    repo.delete_document(V, P)
    repo.delete_document(V, P)  # no-op
    assert repo.current_hash(V, P) is None


def test_in_memory_queue_rules() -> None:
    t = [NOW]
    q = InMemoryJobQueue(clock=lambda: t[0])
    j1 = q.enqueue(Upsert(vault=V, path=P, origin="vault"))
    assert q.enqueue(Remove(vault=V, path=P)) == j1  # replaces pending payload
    claimed = q.claim(timedelta(minutes=5))
    assert claimed and claimed.job == Remove(vault=V, path=P) and claimed.attempt == 1
    j2 = q.enqueue(Upsert(vault=V, path=P, origin="vault"))  # new pending behind the running one
    assert j2 != j1 and q.claim(timedelta(minutes=5)) is None  # same path is running
    d = q.fail(j1, ModelUnavailable(detail="down"))
    assert isinstance(d, RetryAt) and d.attempt == 1
    assert isinstance(q.fail(q.claim(timedelta(minutes=5)).job_id, NotUtf8(path=P)), GaveUp)  # type: ignore[union-attr]
    q.enqueue(Recluster(vault=V))
    q.enqueue(Recluster(vault=V))
    assert q.counts()[JobState.PENDING] == 2  # j1 (retry) + one recluster


def test_fake_llm_outputs() -> None:
    note = ParsedNote(path=P, title="Ideas", frontmatter={}, tags=(), wikilinks=(), headings=(), body="",
                      body_text="pricing pricing strategy subscription tiers", content_hash=ContentHash("h"))
    llm = FakeLanguageModel()
    assert llm.summarize(note).summary.startswith("Ideas")
    assert llm.extract_topics(note)[0].name == "pricing"


# ---- HTTP skeleton ----------------------------------------------------------------------
def test_routes_exist_and_return_501() -> None:
    c = TestClient(create_app())
    assert c.get("/api/search", params={"q": "churn"}).status_code == 501
    assert c.get("/api/graph").status_code == 501
    assert c.get(f"/api/graph/local/doc:{D1}", params={"depth": 2}).status_code == 501
    assert c.get("/api/graph/local/bogus").status_code == 400
    assert c.get(f"/api/links/{D1}/{D2}").status_code == 501
    assert c.get(f"/api/links/{D1}/{D1}").status_code == 400
    assert c.put(f"/api/links/{D1}/{D2}/feedback", json={"verdict": "hidden"}).status_code == 501
    assert c.post(f"/api/vaults/{V}/scan").status_code == 501
    assert c.post(f"/api/vaults/{V}/recluster").status_code == 501
    assert c.get("/api/jobs/status").status_code == 501
    assert c.get("/api/health").status_code == 501
    assert c.post("/api/uploads", files={"files": ("a.md", b"# A")}).status_code == 501
    paths = set(c.get("/api/openapi.json").json()["paths"])
    assert {"/api/uploads", "/api/vaults/{vault_id}/scan", "/api/search", "/api/graph", "/api/graph/local/{node}",
            "/api/links/{a}/{b}", "/api/links/{a}/{b}/feedback", "/api/vaults/{vault_id}/recluster",
            "/api/health", "/api/jobs/status"} <= paths


# ---- migration (only when a database is provided) -----------------------------------------
@pytest.mark.db
@pytest.mark.skipif(not os.environ.get("ATLAS_TEST_DATABASE_URL"), reason="ATLAS_TEST_DATABASE_URL not set")
def test_migration_applies() -> None:
    from atlas.store.migrate import migrate

    url = os.environ["ATLAS_TEST_DATABASE_URL"]
    migrate(url)
    assert migrate(url) == []  # idempotent
