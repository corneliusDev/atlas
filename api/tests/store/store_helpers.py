"""Builders for store tests."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from psycopg_pool import ConnectionPool

from atlas.types import (
    DEFAULT_VAULT_ID,
    EMBEDDING_DIM,
    ClusterId,
    ContentHash,
    DocumentAggregate,
    DocumentId,
    DocumentPair,
    EmbeddedChunk,
    EmbeddedTopic,
    Embedding,
    SemanticLink,
    VaultId,
    VaultPath,
    WikiLink,
    chunk_id_for,
    document_id_for,
)

V = DEFAULT_VAULT_ID


def vec(*weights: tuple[int, float]) -> Embedding:
    """Unit vector with the given (dimension, weight) components."""
    out = [0.0] * EMBEDDING_DIM
    for i, w in weights:
        out[i] = w
    n = math.sqrt(sum(x * x for x in out)) or 1.0
    return tuple(x / n for x in out)


def doc_id(path: str, vault: VaultId = V) -> DocumentId:
    return document_id_for(vault, VaultPath(path))


def aggregate(
    path: str,
    *,
    content_hash: str = "h1",
    embedding: Embedding | None = None,
    vault: VaultId = V,
    chunks: int = 2,
    topics: tuple[EmbeddedTopic, ...] = (),
    wiki: tuple[str, ...] = (),
    links: tuple[tuple[str, float, str | None], ...] = (),
    cluster: ClusterId | None = None,
    title: str | None = None,
) -> DocumentAggregate:
    did = doc_id(path, vault)
    emb = embedding or vec((0, 1.0))
    semantic = []
    for other_path, score, reason in links:
        other = doc_id(other_path, vault)
        pair = DocumentPair.of(did, other)
        mine, theirs = chunk_id_for(did, 0), chunk_id_for(other, 0)
        evidence = (mine, theirs) if pair.a == did else (theirs, mine)
        semantic.append(SemanticLink(pair=pair, score=score, reason=reason, evidence=evidence))
    return DocumentAggregate(
        vault=vault,
        document_id=did,
        path=VaultPath(path),
        origin="vault",
        content_hash=ContentHash(content_hash),
        title=title or path.removesuffix(".md"),
        frontmatter={"source": path, "n": 1},
        tags=("alpha",),
        summary=f"Summary of {path}",
        doc_embedding=emb,
        chunks=tuple(
            EmbeddedChunk(
                id=chunk_id_for(did, i),
                ordinal=i,
                heading_path=("Top", f"Part {i}"),
                text=f"chunk {i} of {path}",
                embedding=emb,
            )
            for i in range(chunks)
        ),
        topics=topics,
        wiki_links=tuple(WikiLink(source=did, target_name=t, anchor=None) for t in wiki),
        semantic_links=tuple(semantic),
        cluster_id=cluster,
        indexed_at=datetime(2026, 11, 8, 12, 0, tzinfo=UTC),
    )


def scalar(pool: ConnectionPool, query: str, *params: object) -> object:
    with pool.connection() as conn:
        row = conn.execute(query, params).fetchone()
    return None if row is None else row[0]


def rows(pool: ConnectionPool, query: str, *params: object) -> list[tuple[object, ...]]:
    with pool.connection() as conn:
        return list(conn.execute(query, params).fetchall())


def add_vault(pool: ConnectionPool) -> VaultId:
    vid = VaultId(uuid.uuid4())
    with pool.connection() as conn:
        conn.execute("INSERT INTO vaults (id, name, root_path) VALUES (%s, 'other', '/other')", (vid,))
    return vid
