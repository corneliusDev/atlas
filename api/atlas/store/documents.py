"""PgDocumentRepository: the only writer of documents, chunks, topics, document_topics,
wiki_links and semantic_links (PRD Output 4)."""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from atlas.store.pool import clamp01, from_vector, lock_vault, to_vector
from atlas.types import (
    CandidateChunk,
    ChunkId,
    ContentHash,
    DocumentAggregate,
    DocumentId,
    DocumentVector,
    Embedding,
    EmbeddedTopic,
    Neighbor,
    Saved,
    SaveResult,
    Superseded,
    TopicKind,
    VaultId,
    VaultPath,
    document_id_for,
)


def _key(name: str) -> str:
    return name.strip().lower()


class PgDocumentRepository:
    """Implements ports.DocumentRepository on Postgres + pgvector."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ---- reads ---------------------------------------------------------------------
    def current_hash(self, vault: VaultId, path: VaultPath) -> ContentHash | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT content_hash FROM documents WHERE vault_id = %s AND path = %s", (vault, path)
            ).fetchone()
        return ContentHash(row[0]) if row else None

    def nearest_documents(self, vault: VaultId, vector: Embedding, k: int, exclude: VaultPath) -> list[Neighbor]:
        if k <= 0:
            return []
        with self._pool.connection() as conn, conn.transaction():
            # The vault/path filter is applied after the HNSW scan; widen the candidate list so
            # filtering still leaves k rows.
            conn.execute(f"SET LOCAL hnsw.ef_search = {max(40, min(1000, k * 4))}")
            docs = conn.execute(
                """
                SELECT id, path, title, 1 - (doc_embedding <=> %(v)s) AS sim
                FROM documents
                WHERE vault_id = %(vault)s AND path <> %(exclude)s
                ORDER BY doc_embedding <=> %(v)s, id
                LIMIT %(k)s
                """,
                {"v": to_vector(vector), "vault": vault, "exclude": exclude, "k": k},
            ).fetchall()
            if not docs:
                return []
            ids = [r[0] for r in docs]
            chunk_rows = conn.execute(
                "SELECT document_id, id, heading_path, text, embedding FROM chunks"
                " WHERE document_id = ANY(%s) ORDER BY document_id, ordinal",
                (ids,),
            ).fetchall()
        chunks: dict[UUID, list[CandidateChunk]] = {}
        for doc_id, cid, heading_path, text, emb in chunk_rows:
            chunks.setdefault(doc_id, []).append(
                CandidateChunk(id=ChunkId(cid), heading_path=tuple(heading_path), text=text, embedding=from_vector(emb))
            )
        return [
            Neighbor(
                document_id=DocumentId(doc_id),
                path=VaultPath(path),
                title=title,
                doc_score=clamp01(float(sim)),
                chunks=tuple(chunks.get(doc_id, ())),
            )
            for doc_id, path, title, sim in docs
        ]

    def all_document_vectors(self, vault: VaultId) -> list[DocumentVector]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, path, title, summary, doc_embedding FROM documents WHERE vault_id = %s ORDER BY id",
                (vault,),
            ).fetchall()
        return [
            DocumentVector(
                document_id=DocumentId(i), path=VaultPath(p), title=t, summary=s, vector=from_vector(e)
            )
            for i, p, t, s, e in rows
        ]

    # ---- writes --------------------------------------------------------------------
    def save_document(self, aggregate: DocumentAggregate, expected_hash: ContentHash | None) -> SaveResult:
        a = aggregate
        doc = a.document_id
        if doc != document_id_for(a.vault, a.path):
            raise ValueError(f"document_id {doc} != document_id_for(vault, {a.path!r})")
        for link in a.semantic_links:
            if doc not in (link.pair.a, link.pair.b):
                raise ValueError(f"semantic link {link.pair} does not involve document {doc}")

        with self._pool.connection() as conn, conn.transaction():
            lock_vault(conn, a.vault)
            row = conn.execute(
                "SELECT content_hash FROM documents WHERE vault_id = %s AND path = %s FOR UPDATE",
                (a.vault, a.path),
            ).fetchone()
            if row is not None and row[0] != expected_hash:
                return Superseded(stored_hash=ContentHash(row[0]))

            # Upsert in place: never delete+insert (link_feedback cascades from documents).
            conn.execute(
                """
                INSERT INTO documents (id, vault_id, path, origin, content_hash, title, frontmatter,
                                       summary, tags, doc_embedding, cluster_id, indexed_at)
                VALUES (%(id)s, %(vault)s, %(path)s, %(origin)s, %(hash)s, %(title)s, %(fm)s,
                        %(summary)s, %(tags)s, %(emb)s,
                        (SELECT id FROM clusters WHERE id = %(cluster)s AND vault_id = %(vault)s),
                        %(indexed_at)s)
                ON CONFLICT (vault_id, path) DO UPDATE SET
                    origin = EXCLUDED.origin,
                    content_hash = EXCLUDED.content_hash,
                    version = documents.version + 1,
                    title = EXCLUDED.title,
                    frontmatter = EXCLUDED.frontmatter,
                    summary = EXCLUDED.summary,
                    tags = EXCLUDED.tags,
                    doc_embedding = EXCLUDED.doc_embedding,
                    cluster_id = EXCLUDED.cluster_id,
                    indexed_at = EXCLUDED.indexed_at
                """,
                {
                    "id": doc,
                    "vault": a.vault,
                    "path": a.path,
                    "origin": a.origin,
                    "hash": a.content_hash,
                    "title": a.title,
                    "fm": Jsonb(a.frontmatter),
                    "summary": a.summary,
                    "tags": list(a.tags),
                    "emb": to_vector(a.doc_embedding),
                    "cluster": a.cluster_id,
                    "indexed_at": a.indexed_at,
                },
            )
            self._replace_chunks(conn, a)
            self._replace_topics(conn, a)
            self._replace_wiki_links(conn, a)
            self._replace_semantic_links(conn, a)
        return Saved(document_id=doc)

    def delete_document(self, vault: VaultId, path: VaultPath) -> None:
        with self._pool.connection() as conn, conn.transaction():
            lock_vault(conn, vault)
            row = conn.execute(
                "SELECT id FROM documents WHERE vault_id = %s AND path = %s", (vault, path)
            ).fetchone()
            if row is None:
                return
            old_topics = [
                r[0] for r in conn.execute("SELECT topic_id FROM document_topics WHERE document_id = %s", (row[0],))
            ]
            conn.execute("DELETE FROM documents WHERE id = %s", (row[0],))  # cascades
            _delete_orphan_topics(conn, old_topics)

    # ---- save_document parts (all inside the one transaction) --------------------------
    @staticmethod
    def _replace_chunks(conn: psycopg.Connection, a: DocumentAggregate) -> None:
        conn.execute("DELETE FROM chunks WHERE document_id = %s", (a.document_id,))
        if not a.chunks:
            return
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (id, document_id, ordinal, heading_path, heading_text, text, embedding)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        c.id,
                        a.document_id,
                        c.ordinal,
                        list(c.heading_path),
                        " > ".join(c.heading_path),
                        c.text,
                        to_vector(c.embedding),
                    )
                    for c in a.chunks
                ],
            )

    def _replace_topics(self, conn: psycopg.Connection, a: DocumentAggregate) -> None:
        old = [
            r[0] for r in conn.execute("SELECT topic_id FROM document_topics WHERE document_id = %s", (a.document_id,))
        ]
        conn.execute("DELETE FROM document_topics WHERE document_id = %s", (a.document_id,))
        salience: dict[UUID, float] = {}
        for t in a.topics:
            tid = _resolve_topic(conn, a.vault, t, a.topic_merge_threshold)
            if tid is not None:
                salience[tid] = max(salience.get(tid, 0.0), t.salience)
        if salience:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO document_topics (document_id, topic_id, salience) VALUES (%s, %s, %s)",
                    [(a.document_id, tid, clamp01(s)) for tid, s in salience.items()],
                )
        _delete_orphan_topics(conn, [t for t in old if t not in salience])

    @staticmethod
    def _replace_wiki_links(conn: psycopg.Connection, a: DocumentAggregate) -> None:
        conn.execute("DELETE FROM wiki_links WHERE source_doc_id = %s", (a.document_id,))
        rows = [
            (a.document_id, w.target_name, _key(w.target_name), w.anchor, i)
            for i, w in enumerate(a.wiki_links)
            if _key(w.target_name)
        ]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO wiki_links (source_doc_id, target_name, target_key, anchor, ordinal)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    rows,
                )

    @staticmethod
    def _replace_semantic_links(conn: psycopg.Connection, a: DocumentAggregate) -> None:
        doc = a.document_id
        partners = [link.pair.other(doc) for link in a.semantic_links]
        conn.execute(
            """
            DELETE FROM semantic_links
            WHERE (doc_a = %(d)s AND NOT doc_b = ANY(%(p)s::uuid[]))
               OR (doc_b = %(d)s AND NOT doc_a = ANY(%(p)s::uuid[]))
            """,
            {"d": doc, "p": partners},
        )
        if not a.semantic_links:
            return
        with conn.cursor() as cur:
            # Skip partners that no longer exist (deleted since nearest_documents ran).
            # Keep a stored reason when the LLM produced none and the evidence is unchanged.
            cur.executemany(
                """
                INSERT INTO semantic_links (vault_id, doc_a, doc_b, score, reason, evidence_chunk_ids, updated_at)
                SELECT %(vault)s, %(a)s, %(b)s, %(score)s, %(reason)s, %(ev)s, now()
                WHERE EXISTS (SELECT 1 FROM documents WHERE id = %(partner)s AND vault_id = %(vault)s)
                ON CONFLICT (doc_a, doc_b) DO UPDATE SET
                    vault_id = EXCLUDED.vault_id,
                    score = EXCLUDED.score,
                    reason = CASE
                        WHEN EXCLUDED.reason IS NULL
                             AND semantic_links.evidence_chunk_ids = EXCLUDED.evidence_chunk_ids
                        THEN semantic_links.reason
                        ELSE EXCLUDED.reason END,
                    evidence_chunk_ids = EXCLUDED.evidence_chunk_ids,
                    updated_at = now()
                """,
                [
                    {
                        "vault": a.vault,
                        "a": link.pair.a,
                        "b": link.pair.b,
                        "partner": link.pair.other(doc),
                        "score": clamp01(link.score),
                        "reason": link.reason,
                        "ev": list(link.evidence),
                    }
                    for link in a.semantic_links
                ],
            )


# ---- topic resolution ------------------------------------------------------------------
def _resolve_topic(conn: psycopg.Connection, vault: VaultId, t: EmbeddedTopic, threshold: float) -> UUID | None:
    """Find or create the topic for one mention; returns its id (None for an empty name).

    TAG topics match by exact name_key only. Other kinds match, in order: an existing non-tag
    topic whose name_key or aliases contain the mention's name or aliases (same kind first);
    then the nearest same-kind topic by embedding with cosine similarity >= threshold. A match
    absorbs the mention's name and aliases into its aliases. Callers hold the vault lock."""
    key = _key(t.name.lstrip("#") if t.kind is TopicKind.TAG else t.name)
    if not key:
        return None
    if t.kind is TopicKind.TAG:
        row = conn.execute(
            """
            INSERT INTO topics (vault_id, canonical_name, name_key, kind)
            VALUES (%s, %s, %s, 'tag')
            ON CONFLICT (vault_id, kind, name_key) DO UPDATE SET canonical_name = topics.canonical_name
            RETURNING id
            """,
            (vault, key, key),
        ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    names = sorted({key, *(_key(x) for x in t.aliases)} - {""})
    emb = to_vector(t.embedding) if t.embedding is not None else None

    row = conn.execute(
        """
        SELECT id FROM topics
        WHERE vault_id = %(vault)s AND kind <> 'tag'
          AND (name_key = ANY(%(names)s) OR aliases && %(names)s::text[])
        ORDER BY (kind = %(kind)s) DESC, (name_key = %(key)s) DESC, created_at, id
        LIMIT 1
        """,
        {"vault": vault, "names": names, "kind": t.kind.value, "key": key},
    ).fetchone()
    if row is None and emb is not None:
        cand = conn.execute(
            """
            SELECT id, 1 - (embedding <=> %(e)s) FROM topics
            WHERE vault_id = %(vault)s AND kind = %(kind)s AND embedding IS NOT NULL
            ORDER BY embedding <=> %(e)s, id
            LIMIT 1
            """,
            {"vault": vault, "kind": t.kind.value, "e": emb},
        ).fetchone()
        if cand is not None and float(cand[1]) >= threshold:
            row = (cand[0],)

    if row is not None:
        conn.execute(
            """
            UPDATE topics SET
                aliases = ARRAY(SELECT DISTINCT x FROM unnest(aliases || %(names)s::text[]) AS x
                                WHERE x <> name_key ORDER BY x),
                embedding = COALESCE(embedding, %(e)s)
            WHERE id = %(id)s
            """,
            {"names": names, "e": emb, "id": row[0]},
        )
        return UUID(str(row[0]))

    created = conn.execute(
        """
        INSERT INTO topics (vault_id, canonical_name, name_key, aliases, kind, embedding)
        VALUES (%(vault)s, %(name)s, %(key)s, %(aliases)s, %(kind)s, %(e)s)
        ON CONFLICT (vault_id, kind, name_key) DO UPDATE SET
            aliases = ARRAY(SELECT DISTINCT x FROM unnest(topics.aliases || EXCLUDED.aliases) AS x ORDER BY x)
        RETURNING id
        """,
        {
            "vault": vault,
            "name": t.name.strip(),
            "key": key,
            "aliases": [n for n in names if n != key],
            "kind": t.kind.value,
            "e": emb,
        },
    ).fetchone()
    assert created is not None
    return UUID(str(created[0]))


def _delete_orphan_topics(conn: psycopg.Connection, topic_ids: Iterable[UUID]) -> None:
    ids = list(topic_ids)
    if ids:
        conn.execute(
            "DELETE FROM topics t WHERE t.id = ANY(%s)"
            " AND NOT EXISTS (SELECT 1 FROM document_topics dt WHERE dt.topic_id = t.id)",
            (ids,),
        )
