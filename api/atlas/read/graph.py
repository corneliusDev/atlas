"""GraphService over Postgres (GR-1..GR-5, SL-2..SL-5).

Loading is a handful of flat per-vault queries (``load_graph_data``); the graph itself is
assembled by the pure ``build_graph`` so the rules are testable without a database:

- Document nodes: every document passing ``GraphFilters`` (tags any-of, clusters, origins,
  indexed_at window). Topic and ghost nodes only appear when attached to a visible document.
- Semantic edges: ``semantic_links`` with ``score >= min_score``, minus pairs the user hid in
  ``link_feedback`` (shown with ``feedback=hidden`` when ``include_hidden``). Confirmed or
  added pairs bypass ``min_score``: a user verdict beats the threshold.
- Manual edges: ``link_feedback`` rows with verdict ``added`` and no semantic link.
- Wiki edges: ``wiki_links`` resolved at read time (``WikiResolver``); unresolved targets
  become ghost nodes "ghost:<normalised name>" when the ghost layer is on.
- Topic edges: ``document_topics`` (weight = salience) when the topic layer is on.
- ``degree`` = number of edges touching the node in the returned view (node size, GR-2);
  colour comes from ``cluster_id`` -> ``clusters[].color``.

``local_graph`` builds the unfiltered graph and keeps the nodes within ``depth`` hops of the
centre (BFS over every edge kind), plus the edges among them.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from atlas.read.db import Connect, Connection, fetch_all, fetch_one
from atlas.read.wikilinks import DocKey, WikiResolver, normalize_name
from atlas.types import (
    ChunkId,
    ClusterId,
    ClusterInfo,
    Depth,
    DocumentId,
    DocumentNode,
    DocumentPair,
    GhostNode,
    GraphEdge,
    GraphFilters,
    GraphNode,
    GraphStats,
    GraphView,
    LinkEndpoint,
    LinkEvidenceView,
    LinkVerdict,
    NodeKind,
    NodeRef,
    Passage,
    TopicId,
    TopicKind,
    TopicNode,
    VaultId,
    VaultPath,
    node_key,
)

# ---------------------------------------------------------------------------
# Loaded rows (plain values; build_graph is pure over these)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocRow:
    id: DocumentId
    path: VaultPath
    title: str
    summary: str | None
    tags: tuple[str, ...]
    cluster_id: ClusterId | None
    origin: Literal["vault", "upload"]
    indexed_at: datetime


@dataclass(frozen=True)
class SemanticRow:
    pair: DocumentPair
    score: float
    reason: str | None


@dataclass(frozen=True)
class WikiRow:
    source: DocumentId
    target_name: str
    anchor: str | None


@dataclass(frozen=True)
class TopicEdgeRow:
    document_id: DocumentId
    topic_id: TopicId
    salience: float
    name: str
    kind: TopicKind
    cluster_id: ClusterId | None


@dataclass
class GraphData:
    docs: list[DocRow] = field(default_factory=list)
    semantic: list[SemanticRow] = field(default_factory=list)
    feedback: dict[DocumentPair, LinkVerdict] = field(default_factory=dict)
    wiki: list[WikiRow] = field(default_factory=list)
    topics: list[TopicEdgeRow] = field(default_factory=list)
    clusters: list[ClusterInfo] = field(default_factory=list)


def _pair(a: Any, b: Any) -> DocumentPair:
    return DocumentPair.of(DocumentId(a), DocumentId(b))


def load_graph_data(conn: Connection, vault: VaultId, *, with_topics: bool) -> GraphData:
    p = {"vault": vault}
    data = GraphData()
    data.docs = [
        DocRow(
            id=DocumentId(r["id"]),
            path=VaultPath(r["path"]),
            title=r["title"],
            summary=r["summary"],
            tags=tuple(r["tags"] or ()),
            cluster_id=ClusterId(r["cluster_id"]) if r["cluster_id"] else None,
            origin=r["origin"],
            indexed_at=r["indexed_at"],
        )
        for r in fetch_all(
            conn,
            "SELECT id, path, title, summary, tags, cluster_id, origin, indexed_at"
            " FROM documents WHERE vault_id = %(vault)s ORDER BY path",
            p,
        )
    ]
    data.semantic = [
        SemanticRow(pair=_pair(r["doc_a"], r["doc_b"]), score=float(r["score"]), reason=r["reason"])
        for r in fetch_all(
            conn, "SELECT doc_a, doc_b, score, reason FROM semantic_links WHERE vault_id = %(vault)s", p
        )
    ]
    data.feedback = {
        _pair(r["doc_a"], r["doc_b"]): LinkVerdict(r["verdict"])
        for r in fetch_all(conn, "SELECT doc_a, doc_b, verdict FROM link_feedback WHERE vault_id = %(vault)s", p)
    }
    data.wiki = [
        WikiRow(source=DocumentId(r["source_doc_id"]), target_name=r["target_name"], anchor=r["anchor"])
        for r in fetch_all(
            conn,
            "SELECT w.source_doc_id, w.target_name, w.anchor FROM wiki_links w"
            " JOIN documents d ON d.id = w.source_doc_id"
            " WHERE d.vault_id = %(vault)s ORDER BY w.source_doc_id, w.ordinal",
            p,
        )
    ]
    if with_topics:
        data.topics = [
            TopicEdgeRow(
                document_id=DocumentId(r["document_id"]),
                topic_id=TopicId(r["topic_id"]),
                salience=float(r["salience"]),
                name=r["canonical_name"],
                kind=TopicKind(r["kind"]),
                cluster_id=ClusterId(r["cluster_id"]) if r["cluster_id"] else None,
            )
            for r in fetch_all(
                conn,
                "SELECT dt.document_id, dt.topic_id, dt.salience, t.canonical_name, t.kind, t.cluster_id"
                " FROM document_topics dt JOIN topics t ON t.id = dt.topic_id"
                " WHERE t.vault_id = %(vault)s ORDER BY dt.document_id, dt.salience DESC, t.id",
                p,
            )
        ]
    data.clusters = [
        ClusterInfo(id=ClusterId(r["id"]), label=r["label"], color=r["color"], size=int(r["size"]))
        for r in fetch_all(
            conn, "SELECT id, label, color, size FROM clusters WHERE vault_id = %(vault)s ORDER BY size DESC, id", p
        )
    ]
    return data


# ---------------------------------------------------------------------------
# Pure assembly
# ---------------------------------------------------------------------------


def _doc_visible(d: DocRow, f: GraphFilters) -> bool:
    if f.tags and not {t.lower().lstrip("#") for t in f.tags} & set(d.tags):
        return False
    if f.cluster_ids and d.cluster_id not in f.cluster_ids:
        return False
    if f.origins and d.origin not in f.origins:
        return False
    if f.indexed_after and d.indexed_at < f.indexed_after:
        return False
    if f.indexed_before and d.indexed_at > f.indexed_before:
        return False
    return True


def _doc_key(d: DocumentId) -> str:
    return node_key(DocumentNode(id=d))


def build_graph(data: GraphData, filters: GraphFilters) -> GraphView:
    visible = [d for d in data.docs if _doc_visible(d, filters)]
    visible_ids = {d.id for d in visible}
    show_docs = NodeKind.DOCUMENT in filters.layers
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    if show_docs:
        for d in visible:
            k = _doc_key(d.id)
            nodes[k] = GraphNode(
                key=k,
                ref=DocumentNode(id=d.id),
                label=d.title,
                path=d.path,
                summary=d.summary,
                tags=d.tags,
                cluster_id=d.cluster_id,
                indexed_at=d.indexed_at,
            )

        # semantic + manual edges
        semantic_pairs: set[DocumentPair] = set()
        for s in data.semantic:
            semantic_pairs.add(s.pair)
            if s.pair.a not in visible_ids or s.pair.b not in visible_ids:
                continue
            verdict = data.feedback.get(s.pair)
            if verdict is LinkVerdict.HIDDEN and not filters.include_hidden:
                continue
            if verdict not in (LinkVerdict.CONFIRMED, LinkVerdict.ADDED) and s.score < filters.min_score:
                continue
            key = f"semantic:{s.pair.a}:{s.pair.b}"
            edges[key] = GraphEdge(
                key=key,
                kind="semantic",
                source=_doc_key(s.pair.a),
                target=_doc_key(s.pair.b),
                weight=s.score,
                reason=s.reason,
                feedback=verdict,
            )
        for pair, verdict in data.feedback.items():
            if verdict is not LinkVerdict.ADDED or pair in semantic_pairs:
                continue
            if pair.a not in visible_ids or pair.b not in visible_ids:
                continue
            key = f"manual:{pair.a}:{pair.b}"
            edges[key] = GraphEdge(
                key=key, kind="manual", source=_doc_key(pair.a), target=_doc_key(pair.b), weight=1.0, feedback=verdict
            )

        # wiki edges (resolution considers every document, not only visible ones)
        resolver = WikiResolver(DocKey(id=d.id, path=d.path, title=d.title) for d in data.docs)
        show_ghosts = NodeKind.GHOST in filters.layers
        for w in data.wiki:
            if w.source not in visible_ids or not normalize_name(w.target_name):
                continue
            target = resolver.resolve(w.target_name)
            if target is not None:
                if target.id == w.source or target.id not in visible_ids:
                    continue
                tkey = _doc_key(target.id)
            else:
                if not show_ghosts:
                    continue
                ghost = GhostNode(name=normalize_name(w.target_name))
                tkey = node_key(ghost)
                if tkey not in nodes:
                    nodes[tkey] = GraphNode(key=tkey, ref=ghost, label=w.target_name.strip())
            key = f"wiki:{w.source}:{tkey}"
            if key not in edges:
                edges[key] = GraphEdge(
                    key=key, kind="wiki", source=_doc_key(w.source), target=tkey, weight=1.0, anchor=w.anchor
                )

    if NodeKind.TOPIC in filters.layers:
        for t in data.topics:
            if t.document_id not in visible_ids:
                continue
            ref = TopicNode(id=t.topic_id)
            tkey = node_key(ref)
            if tkey not in nodes:
                nodes[tkey] = GraphNode(
                    key=tkey, ref=ref, label=t.name, cluster_id=t.cluster_id, topic_kind=t.kind
                )
            if show_docs:
                key = f"topic:{t.document_id}:{t.topic_id}"
                edges[key] = GraphEdge(
                    key=key, kind="topic", source=_doc_key(t.document_id), target=tkey, weight=t.salience
                )

    clusters = [c for c in data.clusters if not filters.cluster_ids or c.id in filters.cluster_ids]
    return _view(list(nodes.values()), list(edges.values()), clusters, center=None)


def _view(nodes: list[GraphNode], edges: list[GraphEdge], clusters: list[ClusterInfo], center: str | None) -> GraphView:
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.source] = degree.get(e.source, 0) + 1
        degree[e.target] = degree.get(e.target, 0) + 1
    out_nodes = tuple(n.model_copy(update={"degree": degree.get(n.key, 0)}) for n in nodes)
    links = sum(1 for e in edges if e.kind in ("semantic", "manual") or (e.kind == "wiki" and e.target.startswith("doc:")))
    stats = GraphStats(
        documents=sum(1 for n in nodes if n.ref.kind == "document"),
        topics=sum(1 for n in nodes if n.ref.kind == "topic"),
        clusters=len(clusters),
        links=links,
    )
    return GraphView(nodes=out_nodes, edges=tuple(edges), clusters=tuple(clusters), stats=stats, center=center)


def center_key(ref: NodeRef) -> str:
    if isinstance(ref, GhostNode):
        return node_key(GhostNode(name=normalize_name(ref.name)))
    return node_key(ref)


def local_view(full: GraphView, center: str, depth: int) -> GraphView:
    """BFS ``depth`` hops from ``center`` over every edge; induced subgraph of what it reaches.
    Unknown centre -> empty view whose ``center`` is still set (the route answers 404)."""
    keys = {n.key for n in full.nodes}
    if center not in keys:
        return GraphView(nodes=(), edges=(), clusters=(), stats=GraphStats(documents=0, topics=0, clusters=0, links=0), center=center)
    adj: dict[str, list[str]] = {}
    for e in full.edges:
        adj.setdefault(e.source, []).append(e.target)
        adj.setdefault(e.target, []).append(e.source)
    dist = {center: 0}
    queue = deque([center])
    while queue:
        cur = queue.popleft()
        if dist[cur] >= depth:
            continue
        for nxt in adj.get(cur, ()):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    nodes = [n for n in full.nodes if n.key in dist]
    edges = [e for e in full.edges if e.source in dist and e.target in dist]
    used_clusters = {n.cluster_id for n in nodes if n.cluster_id}
    clusters = [c for c in full.clusters if c.id in used_clusters]
    return _view(nodes, edges, clusters, center=center)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass
class PgGraphService:
    """Implements ``atlas.ports.GraphService``. Read-only."""

    connect: Connect

    def global_graph(self, vault: VaultId, filters: GraphFilters) -> GraphView:
        with self.connect() as conn:
            data = load_graph_data(conn, vault, with_topics=NodeKind.TOPIC in filters.layers)
        return build_graph(data, filters)

    def local_graph(self, vault: VaultId, center: NodeRef, depth: Depth) -> GraphView:
        with self.connect() as conn:
            data = load_graph_data(conn, vault, with_topics=True)
        return local_view(build_graph(data, GraphFilters()), center_key(center), depth)

    def link_evidence(self, vault: VaultId, pair: DocumentPair) -> LinkEvidenceView | None:
        with self.connect() as conn:
            docs = {
                r["id"]: LinkEndpoint(document_id=DocumentId(r["id"]), path=VaultPath(r["path"]), title=r["title"])
                for r in fetch_all(
                    conn,
                    "SELECT id, path, title FROM documents WHERE vault_id = %(v)s AND id IN (%(a)s, %(b)s)",
                    {"v": vault, "a": pair.a, "b": pair.b},
                )
            }
            if pair.a not in docs or pair.b not in docs:
                return None
            link = fetch_one(
                conn,
                "SELECT score, reason, evidence_chunk_ids FROM semantic_links"
                " WHERE vault_id = %(v)s AND doc_a = %(a)s AND doc_b = %(b)s",
                {"v": vault, "a": pair.a, "b": pair.b},
            )
            fb = fetch_one(
                conn,
                "SELECT verdict FROM link_feedback WHERE vault_id = %(v)s AND doc_a = %(a)s AND doc_b = %(b)s",
                {"v": vault, "a": pair.a, "b": pair.b},
            )
            verdict = LinkVerdict(fb["verdict"]) if fb else None
            if link is None:
                if verdict is not LinkVerdict.ADDED:
                    return None
                return LinkEvidenceView(
                    pair=pair, a=docs[pair.a], b=docs[pair.b], origin="manual", score=None, reason=None,
                    a_passage=None, b_passage=None, feedback=verdict,
                )
            evidence = list(link["evidence_chunk_ids"] or [])
            chunks = {
                r["id"]: r
                for r in fetch_all(
                    conn,
                    "SELECT id, document_id, heading_path, text FROM chunks WHERE id = ANY(%(ids)s::uuid[])",
                    {"ids": evidence},
                )
            }

        def passage(idx: int, owner: DocumentId) -> Passage | None:
            if idx >= len(evidence):
                return None
            r = chunks.get(evidence[idx])
            if r is None or r["document_id"] != owner:  # chunk replaced by a re-index
                return None
            return Passage(chunk_id=ChunkId(r["id"]), heading_path=tuple(r["heading_path"] or ()), text=r["text"])

        return LinkEvidenceView(
            pair=pair,
            a=docs[pair.a],
            b=docs[pair.b],
            origin="semantic",
            score=float(link["score"]),
            reason=link["reason"],
            a_passage=passage(0, pair.a),
            b_passage=passage(1, pair.b),
            feedback=verdict,
        )
