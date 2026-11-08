"""Hybrid search (SR-1): Postgres full text fused with pgvector similarity by RRF.

1. Keyword list: chunks matching ``websearch_to_tsquery('english', q)`` ordered by
   ``ts_rank(chunks.tsv, query)``.
2. Semantic list: chunks ordered by cosine distance to the embedded query (pgvector ``<=>``).
   If the EmbeddingModel is down (``ModelPortError``) search degrades to keyword only.
3. Both chunk lists collapse to documents (a document's rank = rank of its best chunk), then
   reciprocal rank fusion: ``score = sum(1 / (RRF_K + rank))`` over the lists a doc is in.
4. The best passage is the keyword chunk when there is one (so highlights exist), else the
   semantic chunk; its snippet comes from ``ts_headline``, HTML-escaped, matches in <mark>.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from atlas.ports import EmbeddingModel, ModelPortError
from atlas.read.db import Connect, Connection, fetch_all, vector_literal
from atlas.types import (
    ChunkId,
    ClusterId,
    DocumentId,
    DocumentNode,
    SearchHit,
    SearchQuery,
    VaultId,
    VaultPath,
)

RRF_K = 60
_START, _STOP = "\x02", "\x03"  # sentinels: escaped text first, then swapped for <mark>
_HEADLINE_OPTS = (
    f"StartSel={_START}, StopSel={_STOP}, MaxWords=40, MinWords=15, ShortWord=2, "
    'MaxFragments=2, FragmentDelimiter=" … "'
)


def _filters(query: SearchQuery, params: dict[str, Any]) -> str:
    sql = ""
    if query.tags:
        params["tags"] = sorted(t.lower().lstrip("#") for t in query.tags)
        sql += " AND d.tags && %(tags)s::text[]"
    if query.cluster_ids:
        params["clusters"] = sorted(query.cluster_ids)
        sql += " AND d.cluster_id = ANY(%(clusters)s::uuid[])"
    return sql


def render_snippet(raw: str) -> str:
    """ts_headline output -> plain text with matches in <mark>, safe to inject as HTML."""
    text = " ".join(html.escape(raw, quote=False).split())
    return text.replace(_START, "<mark>").replace(_STOP, "</mark>")


@dataclass
class _Ranked:
    rank: int
    chunk: ChunkId


def collapse_to_documents(rows: list[tuple[DocumentId, ChunkId]]) -> dict[DocumentId, _Ranked]:
    """Chunk-ranked rows (best first) -> 1-based document ranks keyed by best chunk."""
    out: dict[DocumentId, _Ranked] = {}
    for doc, chunk in rows:
        if doc not in out:
            out[doc] = _Ranked(rank=len(out) + 1, chunk=chunk)
    return out


def fuse(
    keyword: dict[DocumentId, _Ranked], semantic: dict[DocumentId, _Ranked], limit: int
) -> list[tuple[DocumentId, float, _Ranked | None, _Ranked | None]]:
    docs = set(keyword) | set(semantic)
    scored = []
    for d in docs:
        kw, sem = keyword.get(d), semantic.get(d)
        score = (1.0 / (RRF_K + kw.rank) if kw else 0.0) + (1.0 / (RRF_K + sem.rank) if sem else 0.0)
        scored.append((d, score, kw, sem))
    scored.sort(key=lambda t: (-t[1], min(r.rank for r in (t[2], t[3]) if r), str(t[0])))
    return scored[:limit]


@dataclass
class PgSearchService:
    """Implements ``atlas.ports.SearchService``."""

    connect: Connect
    embedder: EmbeddingModel
    candidate_pool: int = 100  # chunks fetched per list before collapsing to documents

    def search(self, vault: VaultId, query: SearchQuery) -> list[SearchHit]:
        text = query.text.strip()
        if not text:
            return []
        pool = max(self.candidate_pool, query.limit * 5)
        vector = self._embed(text)
        with self.connect() as conn:
            keyword = collapse_to_documents(self._keyword(conn, vault, query, text, pool))
            semantic = collapse_to_documents(self._semantic(conn, vault, query, vector, pool)) if vector else {}
            fused = fuse(keyword, semantic, query.limit)
            if not fused:
                return []
            hits = self._hydrate(conn, text, fused)
        return hits

    def _embed(self, text: str) -> str | None:
        try:
            vectors = self.embedder.embed([text])
        except ModelPortError:
            return None
        return vector_literal(vectors[0]) if vectors else None

    def _keyword(
        self, conn: Connection, vault: VaultId, query: SearchQuery, text: str, pool: int
    ) -> list[tuple[DocumentId, ChunkId]]:
        params: dict[str, Any] = {"vault": vault, "q": text, "pool": pool}
        sql = f"""
            SELECT c.document_id, c.id AS chunk_id
            FROM chunks c
            JOIN documents d ON d.id = c.document_id,
                 websearch_to_tsquery('english', %(q)s) AS q
            WHERE d.vault_id = %(vault)s AND c.tsv @@ q {_filters(query, params)}
            ORDER BY ts_rank(c.tsv, q) DESC, c.id
            LIMIT %(pool)s
        """
        return [(DocumentId(r["document_id"]), ChunkId(r["chunk_id"])) for r in fetch_all(conn, sql, params)]

    def _semantic(
        self, conn: Connection, vault: VaultId, query: SearchQuery, vector: str, pool: int
    ) -> list[tuple[DocumentId, ChunkId]]:
        params: dict[str, Any] = {"vault": vault, "vec": vector, "pool": pool}
        sql = f"""
            SELECT c.document_id, c.id AS chunk_id
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.vault_id = %(vault)s {_filters(query, params)}
            ORDER BY c.embedding <=> %(vec)s::vector
            LIMIT %(pool)s
        """
        return [(DocumentId(r["document_id"]), ChunkId(r["chunk_id"])) for r in fetch_all(conn, sql, params)]

    def _hydrate(
        self, conn: Connection, text: str, fused: list[tuple[DocumentId, float, _Ranked | None, _Ranked | None]]
    ) -> list[SearchHit]:
        chosen: list[tuple[UUID, UUID]] = []
        for doc, _, kw, sem in fused:
            best = kw or sem
            assert best is not None
            chosen.append((doc, best.chunk))
        rows = fetch_all(
            conn,
            """
            SELECT d.id AS document_id, d.path, d.title, d.cluster_id, c.id AS chunk_id, c.heading_path,
                   ts_headline('english', c.text, websearch_to_tsquery('english', %(q)s), %(opts)s) AS snippet
            FROM unnest(%(docs)s::uuid[], %(chunks)s::uuid[]) AS t(doc_id, chunk_id)
            JOIN documents d ON d.id = t.doc_id
            JOIN chunks c ON c.id = t.chunk_id
            """,
            {
                "q": text,
                "opts": _HEADLINE_OPTS,
                "docs": [d for d, _ in chosen],
                "chunks": [c for _, c in chosen],
            },
        )
        by_doc = {r["document_id"]: r for r in rows}
        hits: list[SearchHit] = []
        for doc, score, kw, sem in fused:
            r = by_doc.get(doc)
            if r is None:  # deleted between the two queries
                continue
            hits.append(
                SearchHit(
                    node=DocumentNode(id=doc),
                    document_id=doc,
                    path=VaultPath(r["path"]),
                    title=r["title"],
                    chunk_id=ChunkId(r["chunk_id"]),
                    heading_path=tuple(r["heading_path"] or ()),
                    snippet=render_snippet(r["snippet"] or ""),
                    score=score,
                    keyword_rank=kw.rank if kw else None,
                    semantic_rank=sem.rank if sem else None,
                    cluster_id=ClusterId(r["cluster_id"]) if r["cluster_id"] else None,
                )
            )
        return hits
