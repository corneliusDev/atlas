"""PgDocumentRepository / PgClusterRepository / PgLinkFeedbackRepository against real Postgres."""

from __future__ import annotations

import uuid

import pytest
from psycopg_pool import ConnectionPool
from store_helpers import V, add_vault, aggregate, doc_id, rows, scalar, vec

from atlas import ports
from atlas.store import PgClusterRepository, PgDocumentRepository, PgLinkFeedbackRepository, UnknownDocumentError
from atlas.types import (
    ClusterAssignment,
    ClusterCentroid,
    ClusterId,
    ClusterLabel,
    ContentHash,
    DocumentCluster,
    DocumentPair,
    EmbeddedTopic,
    LinkVerdict,
    Saved,
    Superseded,
    TopicKind,
    VaultPath,
    chunk_id_for,
)


@pytest.fixture
def repo(pool: ConnectionPool) -> PgDocumentRepository:
    return PgDocumentRepository(pool)


def test_adapters_satisfy_ports(pool: ConnectionPool) -> None:
    _d: ports.DocumentRepository = PgDocumentRepository(pool)
    _c: ports.ClusterRepository = PgClusterRepository(pool)
    _f: ports.LinkFeedbackRepository = PgLinkFeedbackRepository(pool)


# ---- save_document -----------------------------------------------------------------------
def test_save_new_document_writes_everything(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    assert repo.save_document(aggregate("b.md"), None) == Saved(document_id=doc_id("b.md"))
    agg = aggregate(
        "a.md",
        chunks=3,
        wiki=("B", "Ghost Note"),
        links=(("b.md", 0.8, "Both about alpha"),),
        topics=(EmbeddedTopic(name="Machine Learning", kind=TopicKind.CONCEPT, salience=0.9, embedding=vec((5, 1.0))),),
    )
    assert repo.save_document(agg, None) == Saved(document_id=agg.document_id)

    assert repo.current_hash(V, VaultPath("a.md")) == ContentHash("h1")
    assert repo.current_hash(V, VaultPath("missing.md")) is None
    assert scalar(pool, "SELECT count(*) FROM chunks WHERE document_id = %s", agg.document_id) == 3
    assert rows(pool, "SELECT heading_text, ordinal FROM chunks WHERE document_id = %s ORDER BY ordinal LIMIT 1", agg.document_id) == [
        ("Top > Part 0", 0)
    ]
    assert rows(pool, "SELECT target_name, target_key, ordinal FROM wiki_links ORDER BY ordinal") == [
        ("B", "b", 0),
        ("Ghost Note", "ghost note", 1),
    ]
    assert rows(pool, "SELECT canonical_name, name_key, kind FROM topics") == [("Machine Learning", "machine learning", "concept")]
    pair = DocumentPair.of(agg.document_id, doc_id("b.md"))
    assert rows(pool, "SELECT doc_a, doc_b, reason FROM semantic_links") == [(pair.a, pair.b, "Both about alpha")]
    fm, version, tags = rows(pool, "SELECT frontmatter, version, tags FROM documents WHERE id = %s", agg.document_id)[0]
    assert fm == {"source": "a.md", "n": 1} and version == 1 and tags == ["alpha"]


def test_superseded_when_stored_hash_differs(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    assert isinstance(repo.save_document(aggregate("a.md", content_hash="h1"), None), Saved)
    # Job started when the doc was absent, but another job saved h1 meanwhile.
    assert repo.save_document(aggregate("a.md", content_hash="h2"), None) == Superseded(stored_hash=ContentHash("h1"))
    # Job read a stale hash.
    assert repo.save_document(aggregate("a.md", content_hash="h3"), ContentHash("h0")) == Superseded(
        stored_hash=ContentHash("h1")
    )
    assert repo.current_hash(V, VaultPath("a.md")) == "h1"
    assert scalar(pool, "SELECT version FROM documents") == 1
    # Correct expected hash: saved in place, version bumped, same id.
    assert repo.save_document(aggregate("a.md", content_hash="h2", chunks=1), ContentHash("h1")) == Saved(
        document_id=doc_id("a.md")
    )
    assert repo.current_hash(V, VaultPath("a.md")) == "h2"
    assert rows(pool, "SELECT id, version FROM documents") == [(doc_id("a.md"), 2)]
    assert scalar(pool, "SELECT count(*) FROM chunks") == 1


def test_resave_keeps_link_feedback_and_replaces_children(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    repo.save_document(aggregate("b.md"), None)
    repo.save_document(aggregate("c.md"), None)
    repo.save_document(aggregate("a.md", wiki=("B", "C"), links=(("b.md", 0.7, "r1"), ("c.md", 0.6, "r2"))), None)
    pair_ab = DocumentPair.of(doc_id("a.md"), doc_id("b.md"))
    PgLinkFeedbackRepository(pool).record(V, pair_ab, LinkVerdict.CONFIRMED)

    repo.save_document(aggregate("a.md", content_hash="h2", wiki=("C",), links=(("b.md", 0.9, None),)), ContentHash("h1"))

    assert scalar(pool, "SELECT verdict FROM link_feedback") == "confirmed"  # in-place upsert, no cascade
    assert rows(pool, "SELECT target_name FROM wiki_links") == [("C",)]
    # a-c dropped; a-b updated; reason kept because the LLM gave none and evidence is unchanged.
    assert rows(pool, "SELECT doc_a, doc_b, score, reason FROM semantic_links") == [(pair_ab.a, pair_ab.b, pytest.approx(0.9), "r1")]


def test_semantic_links_replaced_including_links_from_other_docs(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    repo.save_document(aggregate("a.md"), None)
    repo.save_document(aggregate("b.md", links=(("a.md", 0.7, "x"),)), None)
    assert scalar(pool, "SELECT count(*) FROM semantic_links") == 1
    # a re-indexes without b in its top-k: every link involving a is replaced.
    repo.save_document(aggregate("a.md", content_hash="h2"), ContentHash("h1"))
    assert scalar(pool, "SELECT count(*) FROM semantic_links") == 0


def test_semantic_link_to_missing_partner_is_skipped(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    repo.save_document(aggregate("b.md"), None)
    repo.save_document(aggregate("a.md", links=(("b.md", 0.7, None), ("gone.md", 0.9, None))), None)
    assert scalar(pool, "SELECT count(*) FROM semantic_links") == 1


def test_scores_are_clamped(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    repo.save_document(aggregate("b.md"), None)
    repo.save_document(aggregate("a.md", links=(("b.md", 1.0000002, None),)), None)
    assert scalar(pool, "SELECT score FROM semantic_links") == pytest.approx(1.0)


def test_save_rejects_wrong_document_id(repo: PgDocumentRepository) -> None:
    agg = aggregate("a.md").model_copy(update={"path": VaultPath("other.md")})
    with pytest.raises(ValueError):
        repo.save_document(agg, None)


# ---- topics ------------------------------------------------------------------------------
def test_topic_merge_by_name_alias_embedding_and_tags(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    ml = vec((5, 1.0))
    repo.save_document(
        aggregate(
            "a.md",
            topics=(
                EmbeddedTopic(name="Machine Learning", kind=TopicKind.CONCEPT, salience=0.9, aliases=("ML",), embedding=ml),
                EmbeddedTopic(name="pricing", kind=TopicKind.TAG, salience=1.0),
            ),
        ),
        None,
    )
    repo.save_document(
        aggregate(
            "b.md",
            topics=(
                # exact canonical name, different case/space
                EmbeddedTopic(name="  machine learning ", kind=TopicKind.CONCEPT, salience=0.5, embedding=ml),
                # alias match
                EmbeddedTopic(name="ml", kind=TopicKind.CONCEPT, salience=0.7, embedding=vec((9, 1.0))),
                # tag: exact name only, never merged with a concept
                EmbeddedTopic(name="#Pricing", kind=TopicKind.TAG, salience=1.0),
                EmbeddedTopic(name="machine learning", kind=TopicKind.TAG, salience=1.0),
            ),
        ),
        None,
    )
    repo.save_document(
        aggregate(
            "c.md",
            # embedding similarity >= 0.88 to "Machine Learning"
            topics=(
                EmbeddedTopic(
                    name="Statistical learning", kind=TopicKind.CONCEPT, salience=0.4, embedding=vec((5, 1.0), (6, 0.2))
                ),
                # dissimilar embedding: new topic
                EmbeddedTopic(name="Kyoto", kind=TopicKind.CONCEPT, salience=0.4, embedding=vec((7, 1.0))),
            ),
        ),
        None,
    )
    topics = rows(pool, "SELECT canonical_name, kind, aliases FROM topics ORDER BY kind, name_key")
    assert topics == [
        ("Kyoto", "concept", []),
        ("Machine Learning", "concept", ["ml", "statistical learning"]),
        ("machine learning", "tag", []),
        ("pricing", "tag", []),
    ]
    # b's two mentions of ML collapse into one edge with max salience
    b_edges = rows(
        pool,
        "SELECT t.name_key, t.kind, dt.salience FROM document_topics dt JOIN topics t ON t.id = dt.topic_id"
        " WHERE dt.document_id = %s ORDER BY t.kind, t.name_key",
        doc_id("b.md"),
    )
    assert b_edges == [
        ("machine learning", "concept", pytest.approx(0.7)),
        ("machine learning", "tag", 1.0),
        ("pricing", "tag", 1.0),
    ]


def test_orphan_topics_removed_on_resave_and_delete(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    t_shared = EmbeddedTopic(name="shared", kind=TopicKind.CONCEPT, salience=0.5, embedding=vec((1, 1.0)))
    t_only = EmbeddedTopic(name="only-a", kind=TopicKind.CONCEPT, salience=0.5, embedding=vec((2, 1.0)))
    repo.save_document(aggregate("a.md", topics=(t_shared, t_only)), None)
    repo.save_document(aggregate("b.md", topics=(t_shared,)), None)
    repo.save_document(aggregate("a.md", content_hash="h2", topics=(t_shared,)), ContentHash("h1"))
    assert rows(pool, "SELECT name_key FROM topics") == [("shared",)]
    repo.delete_document(V, VaultPath("a.md"))
    assert rows(pool, "SELECT name_key FROM topics") == [("shared",)]
    repo.delete_document(V, VaultPath("b.md"))
    assert scalar(pool, "SELECT count(*) FROM topics") == 0


# ---- delete ------------------------------------------------------------------------------
def test_delete_is_idempotent_and_cascades(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    repo.save_document(aggregate("b.md"), None)
    repo.save_document(aggregate("a.md", wiki=("B",), links=(("b.md", 0.7, None),)), None)
    PgLinkFeedbackRepository(pool).record(V, DocumentPair.of(doc_id("a.md"), doc_id("b.md")), LinkVerdict.HIDDEN)

    repo.delete_document(V, VaultPath("a.md"))
    repo.delete_document(V, VaultPath("a.md"))  # no-op
    repo.delete_document(V, VaultPath("never-existed.md"))  # no-op

    assert repo.current_hash(V, VaultPath("a.md")) is None
    for table in ("semantic_links", "wiki_links", "link_feedback"):
        assert scalar(pool, f"SELECT count(*) FROM {table}") == 0
    assert scalar(pool, "SELECT count(*) FROM chunks") == 2  # b's chunks remain


# ---- reads -------------------------------------------------------------------------------
def test_nearest_documents_ordering(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    other_vault = add_vault(pool)
    repo.save_document(aggregate("self.md", embedding=vec((0, 1.0))), None)
    repo.save_document(aggregate("close.md", embedding=vec((0, 1.0), (1, 0.1))), None)
    repo.save_document(aggregate("mid.md", embedding=vec((0, 1.0), (1, 1.0))), None)
    repo.save_document(aggregate("far.md", embedding=vec((1, 1.0))), None)
    repo.save_document(aggregate("opposite.md", embedding=vec((0, -1.0))), None)
    repo.save_document(aggregate("elsewhere.md", embedding=vec((0, 1.0)), vault=other_vault), None)

    got = repo.nearest_documents(V, vec((0, 1.0)), k=10, exclude=VaultPath("self.md"))
    assert [n.path for n in got] == ["close.md", "mid.md", "far.md", "opposite.md"]
    scores = [n.doc_score for n in got]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == pytest.approx(0.995, abs=1e-3)
    assert scores[1] == pytest.approx(0.7071, abs=1e-3)
    assert scores[2] == pytest.approx(0.0, abs=1e-6)
    assert scores[3] == 0.0  # clamped from -1
    first = got[0]
    assert first.document_id == doc_id("close.md") and first.title == "close" and first.best_match is None
    assert [c.id for c in first.chunks] == [chunk_id_for(first.document_id, 0), chunk_id_for(first.document_id, 1)]
    assert first.chunks[0].heading_path == ("Top", "Part 0")
    assert len(first.chunks[0].embedding) == 768

    assert [n.path for n in repo.nearest_documents(V, vec((0, 1.0)), k=2, exclude=VaultPath("self.md"))] == [
        "close.md",
        "mid.md",
    ]
    assert repo.nearest_documents(V, vec((0, 1.0)), k=0, exclude=VaultPath("self.md")) == []
    assert [n.path for n in repo.nearest_documents(other_vault, vec((0, 1.0)), k=5, exclude=VaultPath("x.md"))] == [
        "elsewhere.md"
    ]


def test_all_document_vectors(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    other_vault = add_vault(pool)
    repo.save_document(aggregate("a.md", embedding=vec((3, 1.0))), None)
    repo.save_document(aggregate("b.md"), None)
    repo.save_document(aggregate("c.md", vault=other_vault), None)
    got = repo.all_document_vectors(V)
    assert sorted(v.path for v in got) == ["a.md", "b.md"]
    assert [v.document_id for v in got] == sorted(v.document_id for v in got)
    a = next(v for v in got if v.path == "a.md")
    assert a.summary == "Summary of a.md" and a.vector[3] == pytest.approx(1.0)


# ---- clusters ----------------------------------------------------------------------------
def test_replace_clusters_and_cluster_id_on_save(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    clusters = PgClusterRepository(pool)
    t = EmbeddedTopic(name="topic", kind=TopicKind.CONCEPT, salience=0.5, embedding=vec((1, 1.0)))
    repo.save_document(aggregate("a.md", topics=(t,)), None)
    repo.save_document(aggregate("b.md", topics=(t,)), None)
    repo.save_document(aggregate("c.md"), None)
    c1, c2 = ClusterId(uuid.uuid4()), ClusterId(uuid.uuid4())
    assignment = ClusterAssignment(
        centroids=(
            ClusterCentroid(cluster_id=c1, centroid=vec((0, 1.0)), color="#ff0000"),
            ClusterCentroid(cluster_id=c2, centroid=vec((1, 1.0)), color="#00ff00"),
        ),
        members=(
            DocumentCluster(document_id=doc_id("a.md"), cluster_id=c1),
            DocumentCluster(document_id=doc_id("b.md"), cluster_id=c1),
            DocumentCluster(document_id=doc_id("c.md"), cluster_id=None),
        ),
    )
    clusters.replace_clusters(V, assignment, [ClusterLabel(cluster_id=c1, label="Alpha")])
    assert {c.cluster_id: c.color for c in clusters.centroids(V)} == {c1: "#ff0000", c2: "#00ff00"}
    assert sorted(rows(pool, "SELECT label, size FROM clusters"), key=str) == sorted([("Alpha", 2), (None, 0)], key=str)
    assert rows(pool, "SELECT path, cluster_id FROM documents ORDER BY path") == [("a.md", c1), ("b.md", c1), ("c.md", None)]
    assert scalar(pool, "SELECT cluster_id FROM topics") == c1

    # Pipeline assigns the nearest cluster on save.
    repo.save_document(aggregate("d.md", cluster=c2), None)
    assert scalar(pool, "SELECT cluster_id FROM documents WHERE path = 'd.md'") == c2

    # A re-cluster that drops c2 clears d's assignment; saving with a vanished cluster id stores NULL.
    c3 = ClusterId(uuid.uuid4())
    clusters.replace_clusters(
        V,
        ClusterAssignment(
            centroids=(ClusterCentroid(cluster_id=c3, centroid=vec((2, 1.0)), color="#0000ff"),),
            members=(DocumentCluster(document_id=doc_id("a.md"), cluster_id=c3),),
        ),
        [],
    )
    assert rows(pool, "SELECT path, cluster_id FROM documents ORDER BY path") == [
        ("a.md", c3),
        ("b.md", None),
        ("c.md", None),
        ("d.md", None),
    ]
    assert scalar(pool, "SELECT cluster_id FROM topics") == c3
    repo.save_document(aggregate("e.md", cluster=c2), None)
    assert scalar(pool, "SELECT cluster_id FROM documents WHERE path = 'e.md'") is None
    assert [c.cluster_id for c in clusters.centroids(V)] == [c3]


def test_replace_clusters_rejects_unknown_member_cluster(pool: ConnectionPool) -> None:
    with pytest.raises(ValueError):
        PgClusterRepository(pool).replace_clusters(
            V,
            ClusterAssignment(centroids=(), members=(DocumentCluster(document_id=doc_id("a.md"), cluster_id=ClusterId(uuid.uuid4())),)),
            [],
        )


# ---- feedback ----------------------------------------------------------------------------
def test_feedback_upsert_is_idempotent(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    repo.save_document(aggregate("a.md"), None)
    repo.save_document(aggregate("b.md"), None)
    fb = PgLinkFeedbackRepository(pool)
    pair = DocumentPair.of(doc_id("a.md"), doc_id("b.md"))
    fb.record(V, pair, LinkVerdict.CONFIRMED)
    fb.record(V, pair, LinkVerdict.CONFIRMED)
    assert rows(pool, "SELECT verdict FROM link_feedback") == [("confirmed",)]
    fb.record(V, pair, LinkVerdict.HIDDEN)
    assert rows(pool, "SELECT doc_a, doc_b, verdict FROM link_feedback") == [(pair.a, pair.b, "hidden")]


def test_feedback_unknown_document(repo: PgDocumentRepository, pool: ConnectionPool) -> None:
    repo.save_document(aggregate("a.md"), None)
    other_vault = add_vault(pool)
    repo.save_document(aggregate("x.md", vault=other_vault), None)
    fb = PgLinkFeedbackRepository(pool)
    with pytest.raises(UnknownDocumentError):
        fb.record(V, DocumentPair.of(doc_id("a.md"), doc_id("ghost.md")), LinkVerdict.ADDED)
    with pytest.raises(UnknownDocumentError):  # cross-vault pair
        fb.record(V, DocumentPair.of(doc_id("a.md"), doc_id("x.md", other_vault)), LinkVerdict.ADDED)
    assert scalar(pool, "SELECT count(*) FROM link_feedback") == 0
