"""Track E read services against a real Postgres + pgvector (seeded by fixtures/read_seed.sql).

Runs only when ATLAS_TEST_DATABASE_URL is set; creates and drops its own scratch database.
    docker run -d --name atlas-track-e-db -e POSTGRES_USER=atlas -e POSTGRES_PASSWORD=atlas \\
        -e POSTGRES_DB=atlas -p 55435:5432 pgvector/pgvector:pg16
    ATLAS_TEST_DATABASE_URL=postgresql://atlas:atlas@localhost:55435/atlas pytest tests/test_read_pg.py
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from atlas.http.app import AppServices, create_app
from atlas.ports import ModelUnavailableError
from atlas.read.db import Connect, connect_factory
from atlas.read.documents import FileRoots, PgDocumentReader
from atlas.read.graph import PgGraphService
from atlas.read.health import PgHealthCheck
from atlas.read.jobs import PgJobsStatusReader
from atlas.read.search import PgSearchService
from atlas.read.vaults import PgVaultReader
from atlas.store.migrate import migrate
from atlas.types import (
    DEFAULT_VAULT_ID,
    EMBEDDING_DIM,
    ClusterId,
    DocumentId,
    DocumentNode,
    DocumentPair,
    Embedding,
    FileStatus,
    GhostNode,
    GraphFilters,
    JobState,
    LinkVerdict,
    NodeKind,
    SearchQuery,
    TopicId,
    TopicNode,
    VaultId,
)

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not os.environ.get("ATLAS_TEST_DATABASE_URL"), reason="ATLAS_TEST_DATABASE_URL not set"),
]

V = DEFAULT_VAULT_ID
V2 = VaultId(UUID("00000000-0000-0000-0000-000000000002"))
P = DocumentId(UUID("00000000-0000-0000-0000-000000000a01"))  # pricing
C = DocumentId(UUID("00000000-0000-0000-0000-000000000a02"))  # churn
K = DocumentId(UUID("00000000-0000-0000-0000-000000000a03"))  # kyoto (upload)
R = DocumentId(UUID("00000000-0000-0000-0000-000000000a04"))  # ramen
X = DocumentId(UUID("00000000-0000-0000-0000-000000000b01"))  # other vault
C1 = ClusterId(UUID("00000000-0000-0000-0000-00000000c001"))
T_RET = TopicId(UUID("00000000-0000-0000-0000-0000000070a1"))
T_TRAVEL = TopicId(UUID("00000000-0000-0000-0000-0000000070a2"))
SEED = Path(__file__).parent / "fixtures" / "read_seed.sql"


def onehot(i: int) -> Embedding:
    """Same as pg_temp.onehot(i) in the seed (1-based axis)."""
    return tuple(1.0 if g == i else 0.0 for g in range(1, EMBEDDING_DIM + 1))


class AxisEmbedder:
    """EmbeddingModel fake: every text embeds to one fixed axis (or raises)."""

    def __init__(self, axis: int, fail: bool = False) -> None:
        self.axis, self.fail = axis, fail

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if self.fail:
            raise ModelUnavailableError("ollama down")
        return [onehot(self.axis) for _ in texts]


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    admin_url = os.environ["ATLAS_TEST_DATABASE_URL"]
    name = f"atlas_read_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(admin_url, dbname=name)
    try:
        migrate(url)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SEED.read_text(encoding="utf-8").encode())
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture(scope="module")
def connect(db_url: str) -> Connect:
    return connect_factory(db_url)


# ---- search --------------------------------------------------------------------------------
def test_hybrid_search_fuses_keyword_and_semantic(connect: Connect) -> None:
    svc = PgSearchService(connect=connect, embedder=AxisEmbedder(axis=2))  # semantic -> churn doc
    hits = svc.search(V, SearchQuery(text="churn"))
    ids = [h.document_id for h in hits]
    assert X not in ids  # vault isolation
    assert ids[0] == C  # keyword rank 1 or 2 + semantic rank 1
    top = hits[0]
    assert top.semantic_rank == 1 and top.keyword_rank is not None
    assert "<mark>churn</mark>" in top.snippet.lower()
    assert top.heading_path == ("Cohorts",)
    assert top.node == DocumentNode(id=C) and top.cluster_id == C1
    pricing = next(h for h in hits if h.document_id == P)
    assert pricing.keyword_rank is not None
    assert "seats &lt; 10 &amp; monthly" in pricing.snippet  # HTML-escaped around the <mark>s
    assert hits == sorted(hits, key=lambda h: -h.score)


def test_semantic_only_match_and_filters(connect: Connect) -> None:
    svc = PgSearchService(connect=connect, embedder=AxisEmbedder(axis=4))  # semantic -> ramen
    hits = svc.search(V, SearchQuery(text="soup", limit=2))
    assert len(hits) == 2
    assert hits[0].document_id == R and hits[0].keyword_rank is None and hits[0].semantic_rank == 1
    assert "<mark>" not in hits[0].snippet and hits[0].snippet

    tagged = svc.search(V, SearchQuery(text="churn", tags=frozenset({"product"})))
    assert [h.document_id for h in tagged] == [P]
    clustered = svc.search(V, SearchQuery(text="churn", cluster_ids=frozenset({C1})))
    assert {h.document_id for h in clustered} == {P, C}


def test_search_degrades_to_keyword_when_embeddings_down(connect: Connect) -> None:
    svc = PgSearchService(connect=connect, embedder=AxisEmbedder(axis=1, fail=True))
    hits = svc.search(V, SearchQuery(text="broth"))
    assert [h.document_id for h in hits] == [R]
    assert hits[0].semantic_rank is None and hits[0].keyword_rank == 1
    assert "<mark>broth</mark>" in hits[0].snippet


# ---- global graph ---------------------------------------------------------------------------
def _edges(view: object) -> dict[str, object]:
    return {e.key: e for e in view.edges}  # type: ignore[attr-defined]


def test_global_graph_default(connect: Connect) -> None:
    g = PgGraphService(connect=connect).global_graph(V, GraphFilters())
    keys = {n.key for n in g.nodes}
    assert {f"doc:{d}" for d in (P, C, K, R)} <= keys
    assert f"doc:{X}" not in keys
    assert {"ghost:competitor teardown q3", "ghost:kyoto ryokan list"} <= keys
    assert {f"topic:{T_RET}", f"topic:{T_TRAVEL}"} <= keys
    e = _edges(g)
    # semantic edges: P-C kept, K-R kept, C-R hidden by feedback
    assert f"semantic:{P}:{C}" in e and f"semantic:{K}:{R}" in e
    assert f"semantic:{C}:{R}" not in e
    # user-added manual edge
    manual = e[f"manual:{P}:{K}"]
    assert manual.kind == "manual" and manual.feedback == LinkVerdict.ADDED  # type: ignore[attr-defined]
    # wiki: title, path and stem resolution; self link dropped; ghosts
    assert f"wiki:{P}:doc:{C}" in e and e[f"wiki:{P}:doc:{C}"].anchor == "Cohorts"  # type: ignore[attr-defined]
    assert f"wiki:{C}:doc:{P}" in e
    assert f"wiki:{R}:doc:{K}" in e
    assert f"wiki:{R}:doc:{R}" not in e
    assert f"wiki:{P}:ghost:competitor teardown q3" in e
    # topic edges weighted by salience
    assert e[f"topic:{C}:{T_RET}"].weight == pytest.approx(0.9)  # type: ignore[attr-defined]
    nodes = {n.key: n for n in g.nodes}
    ghost = nodes["ghost:kyoto ryokan list"]
    assert ghost.ref == GhostNode(name="kyoto ryokan list") and ghost.label == "Kyoto Ryokan List"
    # degree: P has semantic(C), manual(K), wiki->C, wiki<-C, wiki->ghost, topic = 6
    assert nodes[f"doc:{P}"].degree == 6
    assert nodes[f"doc:{P}"].cluster_id == C1 and nodes[f"doc:{P}"].summary
    assert nodes[f"topic:{T_TRAVEL}"].topic_kind is not None
    assert {c.label for c in g.clusters} == {"Product", "Travel"}
    assert g.stats.documents == 4 and g.stats.topics == 2 and g.stats.clusters == 2
    # links = semantic 2 + manual 1 + resolved wiki 3
    assert g.stats.links == 6


def test_global_graph_filters(connect: Connect) -> None:
    svc = PgGraphService(connect=connect)
    g = svc.global_graph(V, GraphFilters(layers=frozenset({NodeKind.DOCUMENT})))
    assert all(n.ref.kind == "document" for n in g.nodes)
    assert not any(e.kind == "topic" or e.target.startswith("ghost:") for e in g.edges)

    g = svc.global_graph(V, GraphFilters(min_score=0.5))
    e = _edges(g)
    assert f"semantic:{P}:{C}" in e and f"semantic:{K}:{R}" not in e
    assert f"manual:{P}:{K}" in e  # manual links ignore min_score

    g = svc.global_graph(V, GraphFilters(include_hidden=True))
    hidden = _edges(g)[f"semantic:{C}:{R}"]
    assert hidden.feedback == LinkVerdict.HIDDEN  # type: ignore[attr-defined]

    g = svc.global_graph(V, GraphFilters(origins=frozenset({"upload"})))
    assert {n.key for n in g.nodes if n.ref.kind == "document"} == {f"doc:{K}"}

    g = svc.global_graph(V, GraphFilters(cluster_ids=frozenset({C1}), layers=frozenset({NodeKind.DOCUMENT})))
    assert {n.key for n in g.nodes} == {f"doc:{P}", f"doc:{C}"}
    assert [c.id for c in g.clusters] == [C1]

    g = svc.global_graph(V, GraphFilters(tags=frozenset({"#Travel", "cooking"}), layers=frozenset({NodeKind.DOCUMENT})))
    assert {n.key for n in g.nodes} == {f"doc:{K}", f"doc:{R}"}

    from datetime import UTC, datetime

    g = svc.global_graph(
        V,
        GraphFilters(
            indexed_after=datetime(2026, 11, 2, tzinfo=UTC),
            indexed_before=datetime(2026, 11, 3, 12, tzinfo=UTC),
            layers=frozenset({NodeKind.DOCUMENT}),
        ),
    )
    assert {n.key for n in g.nodes} == {f"doc:{C}", f"doc:{K}"}


def test_wikilink_to_filtered_out_doc_is_not_a_ghost(connect: Connect) -> None:
    g = PgGraphService(connect=connect).global_graph(V, GraphFilters(tags=frozenset({"product"})))
    keys = {n.key for n in g.nodes}
    assert "ghost:churn analysis" not in keys  # resolves to C even though C is filtered out
    assert "ghost:competitor teardown q3" in keys


# ---- local graph ---------------------------------------------------------------------------
def test_local_graph_depths(connect: Connect) -> None:
    svc = PgGraphService(connect=connect)
    g1 = svc.local_graph(V, DocumentNode(id=R), 1)
    assert g1.center == f"doc:{R}"
    # ramen: semantic K-R, wiki R->K (C-R hidden) -> {R, K}
    assert {n.key for n in g1.nodes} == {f"doc:{R}", f"doc:{K}"}
    g2 = svc.local_graph(V, DocumentNode(id=R), 2)
    keys2 = {n.key for n in g2.nodes}
    assert {f"doc:{P}", "ghost:kyoto ryokan list", f"topic:{T_TRAVEL}"} <= keys2
    assert f"doc:{C}" not in keys2
    g3 = svc.local_graph(V, DocumentNode(id=R), 3)
    assert f"doc:{C}" in {n.key for n in g3.nodes}
    assert all(e.source in {n.key for n in g3.nodes} and e.target in {n.key for n in g3.nodes} for e in g3.edges)


def test_local_graph_ghost_and_topic_centres(connect: Connect) -> None:
    svc = PgGraphService(connect=connect)
    g = svc.local_graph(V, GhostNode(name="Kyoto Ryokan List"), 1)
    assert g.center == "ghost:kyoto ryokan list"
    assert {n.key for n in g.nodes} == {"ghost:kyoto ryokan list", f"doc:{K}"}
    t = svc.local_graph(V, TopicNode(id=T_RET), 1)
    assert {n.key for n in t.nodes} == {f"topic:{T_RET}", f"doc:{P}", f"doc:{C}"}
    missing = svc.local_graph(V, DocumentNode(id=X), 2)  # exists, but in another vault
    assert missing.nodes == () and missing.center == f"doc:{X}"


# ---- link evidence -------------------------------------------------------------------------
def test_link_evidence(connect: Connect) -> None:
    svc = PgGraphService(connect=connect)
    ev = svc.link_evidence(V, DocumentPair.of(C, P))
    assert ev is not None and ev.origin == "semantic"
    assert ev.score == pytest.approx(0.82) and ev.reason == "Both tie pricing decisions to churn."
    assert ev.a.title == "Pricing Strategy" and ev.b.title == "Churn Analysis"
    assert ev.a_passage is not None and ev.a_passage.heading_path == ("Pricing", "Tiers")
    assert ev.b_passage is not None and "cohorts" in ev.b_passage.text.lower()
    assert ev.feedback is None

    manual = svc.link_evidence(V, DocumentPair.of(P, K))
    assert manual is not None and manual.origin == "manual" and manual.score is None
    assert manual.feedback == LinkVerdict.ADDED and manual.a_passage is None

    hidden = svc.link_evidence(V, DocumentPair.of(C, R))
    assert hidden is not None and hidden.feedback == LinkVerdict.HIDDEN

    assert svc.link_evidence(V, DocumentPair.of(P, R)) is None  # no link
    assert svc.link_evidence(V, DocumentPair.of(P, X)) is None  # cross-vault


# ---- document view -------------------------------------------------------------------------
@pytest.fixture()
def roots(tmp_path: Path) -> FileRoots:
    vault_root = tmp_path / "vault"
    (vault_root / "product").mkdir(parents=True)
    (vault_root / "product" / "pricing.md").write_text(
        "---\ntitle: Pricing Strategy\nowner: ana\n---\n# Pricing\n\nSee [[Churn Analysis#Cohorts]].\n", encoding="utf-8"
    )
    up = tmp_path / "uploads" / str(V) / "travel"
    up.mkdir(parents=True)
    (up / "kyoto.md").write_text("# Kyoto\n\nTemples.\n", encoding="utf-8")
    return FileRoots(uploads_root=tmp_path / "uploads", vault_roots={V: vault_root})


def test_document_detail(connect: Connect, roots: FileRoots) -> None:
    reader = PgDocumentReader(connect=connect, roots=roots)
    d = reader.document(V, P)
    assert d is not None
    assert d.title == "Pricing Strategy" and d.origin == "vault"
    assert d.markdown.startswith("# Pricing") and "owner: ana" not in d.markdown
    assert d.frontmatter == {"title": "Pricing Strategy", "owner": "ana"}
    assert d.tags == ["product", "pricing"] and d.cluster_id == C1
    assert [t.name for t in d.topics] == ["Customer Retention"]
    # related: manual (K) first, then semantic C; no hidden
    assert [r.document.id for r in d.related] == [K, C]
    assert d.related[0].score is None and d.related[0].feedback == LinkVerdict.ADDED
    assert d.related[1].reason == "Both tie pricing decisions to churn."
    assert [(b.document.id, b.anchor) for b in d.backlinks] == [(C, None)]
    out = {o.target_name: o.resolved for o in d.outgoing}
    assert out["Churn Analysis"] is not None and out["Churn Analysis"].id == C
    assert out["Competitor Teardown Q3"] is None

    churn = reader.document(V, C)
    assert churn is not None
    assert R not in [r.document.id for r in churn.related]  # hidden link excluded
    assert [b.document.id for b in churn.backlinks] == [P]

    kyoto = reader.document(V, K)
    assert kyoto is not None and kyoto.markdown.startswith("# Kyoto")  # read from uploads root
    assert {b.document.id for b in kyoto.backlinks} == {R}

    ramen = reader.document(V, R)  # file missing on disk -> chunk text fallback
    assert ramen is not None and "twelve hours" in ramen.markdown

    assert reader.document(V, X) is None  # other vault
    assert reader.exists(V, P) and not reader.exists(V, X)


# ---- jobs / vaults / health -----------------------------------------------------------------
def test_jobs_status(connect: Connect) -> None:
    s = PgJobsStatusReader(connect=connect).status(V, 200)
    assert s.counts == {JobState.PENDING: 2, JobState.RUNNING: 1, JobState.DONE: 2, JobState.FAILED: 1}
    files = {f.path: f for f in s.files}
    assert set(files) == {"product/pricing.md", "research/churn.md", "travel/kyoto.md", "cooking/ramen.md"}
    assert files["travel/kyoto.md"].status == FileStatus.INDEXING  # newest job wins
    assert files["travel/kyoto.md"].error is not None  # last attempt timed out
    assert files["product/pricing.md"].status == FileStatus.LINKED
    assert files["product/pricing.md"].outcome is not None and files["product/pricing.md"].outcome.kind == "indexed"
    assert files["research/churn.md"].status == FileStatus.FAILED
    assert files["cooking/ramen.md"].status == FileStatus.QUEUED
    assert [f.path for f in s.files][0] == "travel/kyoto.md"  # most recently updated first
    assert [f.path for f in s.recent_failures] == ["research/churn.md"]
    assert s.recent_failures[0].error.kind == "not_utf8"
    assert s.recluster_pending and not s.idle
    assert len(PgJobsStatusReader(connect=connect).status(V, 1).files) == 1
    other = PgJobsStatusReader(connect=connect).status(V2, 10)
    assert other.idle and other.counts[JobState.FAILED] == 1 and not other.recluster_pending


def test_vaults_and_health(connect: Connect, tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("x")
    reader = PgVaultReader(connect=connect, vault_roots={V: tmp_path})
    vs = {v.id: v for v in reader.vaults()}
    assert vs[V].document_count == 4 and vs[V].mounted
    assert vs[V2].document_count == 1 and not vs[V2].mounted
    assert reader.exists(V) and not reader.exists(VaultId(uuid.uuid4()))

    h = PgHealthCheck(connect=connect, embeddings_ok=lambda: True, llm_model="claude-opus-5-5", version="t").check()
    assert h.status == "ok" and h.database and h.llm == "enabled"
    bad = PgHealthCheck(connect=connect_factory("postgresql://nobody@127.0.0.1:1/x"), embeddings_ok=lambda: True,
                        llm_model=None, version="t").check()
    assert bad.status == "degraded" and not bad.database and bad.llm == "embeddings_only"


# ---- HTTP end to end over the Pg services ----------------------------------------------------
def test_http_over_postgres(connect: Connect, roots: FileRoots) -> None:
    app = create_app(
        AppServices(
            search=PgSearchService(connect=connect, embedder=AxisEmbedder(axis=2)),
            graph=PgGraphService(connect=connect),
            documents=PgDocumentReader(connect=connect, roots=roots),
            jobs=PgJobsStatusReader(connect=connect),
            vaults=PgVaultReader(connect=connect),
        )
    )
    c = TestClient(app)
    r = c.get("/api/search", params={"q": "churn"})
    assert r.status_code == 200 and r.json()["hits"][0]["document_id"] == str(C)
    r = c.get("/api/graph", params=[("layer", "document"), ("min_score", "0.5")])
    assert r.status_code == 200 and all(n["ref"]["kind"] == "document" for n in r.json()["nodes"])
    r = c.get(f"/api/graph/local/doc:{R}", params={"depth": 1})
    assert r.status_code == 200 and r.json()["center"] == f"doc:{R}"
    assert c.get(f"/api/graph/local/doc:{X}").status_code == 404
    r = c.get(f"/api/links/{C}/{P}")
    assert r.status_code == 200 and r.json()["pair"] == {"a": str(P), "b": str(C)}
    assert c.get(f"/api/links/{P}/{R}").status_code == 404
    r = c.get(f"/api/documents/{P}")
    assert r.status_code == 200 and r.json()["title"] == "Pricing Strategy"
    assert c.get(f"/api/documents/{X}").status_code == 404
    assert c.get(f"/api/documents/{X}", params={"vault": str(V2)}).status_code == 200
    r = c.get("/api/jobs/status")
    assert r.status_code == 200 and r.json()["counts"]["pending"] == 2
    assert c.get("/api/vaults").json()["vaults"][0]["id"] == str(V)
