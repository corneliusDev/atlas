"""Document view read model (DV-1 / DV-2): GET /api/documents/{id}.

The raw Markdown is read from disk (vault root for origin="vault", ``<uploads_root>/<vault>/``
for origin="upload") with the YAML frontmatter block removed. When the file is gone or
unreadable the body falls back to the stored chunk texts so the view still renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.http.dto import (
    BacklinkDto,
    DocumentDetail,
    DocumentRef,
    DocumentTopicDto,
    OutgoingWikiLinkDto,
    RelatedDocument,
)
from atlas.read.db import Connect, Connection, fetch_all, fetch_one
from atlas.read.wikilinks import DocKey, WikiResolver
from atlas.types import (
    DEFAULT_VAULT_ID,
    ClusterId,
    DocumentId,
    LinkVerdict,
    TopicId,
    TopicKind,
    VaultId,
    VaultPath,
)


def strip_frontmatter(text: str) -> str:
    """Remove a leading ``---`` YAML block (closed by ``---`` or ``...``). Unclosed = no block."""
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].rstrip() in ("---", "..."):
            return "".join(lines[i + 1 :]).lstrip("\r\n")
    return text


def resolve_under(root: Path, rel: str) -> Path | None:
    """root/rel, or None if it escapes root (defence in depth: paths come from the DB)."""
    try:
        base = root.resolve()
        target = (base / rel).resolve()
    except (OSError, RuntimeError):
        return None
    return target if target.is_relative_to(base) else None


@dataclass
class FileRoots:
    """Where documents live on disk. ``vault_roots`` overrides vaults.root_path per vault."""

    uploads_root: Path
    vault_roots: dict[VaultId, Path] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, vault_root: Path, uploads_root: Path) -> FileRoots:
        return cls(uploads_root=uploads_root, vault_roots={DEFAULT_VAULT_ID: vault_root})

    def file_for(self, vault: VaultId, db_root: str | None, origin: str, path: str) -> Path | None:
        if origin == "upload":
            return resolve_under(self.uploads_root / str(vault), path)
        root = self.vault_roots.get(vault) or (Path(db_root) if db_root else None)
        return resolve_under(root, path) if root else None


@dataclass
class PgDocumentReader:
    """Implements ``atlas.read.protocols.DocumentReader``."""

    connect: Connect
    roots: FileRoots

    def exists(self, vault: VaultId, document_id: DocumentId) -> bool:
        with self.connect() as conn:
            return (
                fetch_one(conn, "SELECT 1 AS x FROM documents WHERE vault_id = %s AND id = %s", (vault, document_id))
                is not None
            )

    def document(self, vault: VaultId, document_id: DocumentId) -> DocumentDetail | None:
        with self.connect() as conn:
            doc = fetch_one(
                conn,
                "SELECT d.*, v.root_path FROM documents d JOIN vaults v ON v.id = d.vault_id"
                " WHERE d.vault_id = %s AND d.id = %s",
                (vault, document_id),
            )
            if doc is None:
                return None
            all_docs = {
                r["id"]: DocKey(id=DocumentId(r["id"]), path=r["path"], title=r["title"])
                for r in fetch_all(conn, "SELECT id, path, title FROM documents WHERE vault_id = %s", (vault,))
            }
            topics = self._topics(conn, document_id)
            related = self._related(conn, vault, document_id, all_docs)
            resolver = WikiResolver(all_docs.values())
            outgoing = self._outgoing(conn, document_id, resolver)
            backlinks = self._backlinks(conn, vault, document_id, resolver, all_docs)
            markdown = self._markdown(conn, vault, doc)

        return DocumentDetail(
            id=DocumentId(doc["id"]),
            vault=VaultId(doc["vault_id"]),
            path=VaultPath(doc["path"]),
            origin=doc["origin"],
            title=doc["title"],
            markdown=markdown,
            frontmatter=doc["frontmatter"] or {},
            summary=doc["summary"],
            tags=list(doc["tags"] or ()),
            cluster_id=ClusterId(doc["cluster_id"]) if doc["cluster_id"] else None,
            indexed_at=doc["indexed_at"],
            topics=topics,
            related=related,
            backlinks=backlinks,
            outgoing=outgoing,
        )

    # ---- pieces -------------------------------------------------------------------
    @staticmethod
    def _ref(k: DocKey) -> DocumentRef:
        return DocumentRef(id=k.id, path=VaultPath(k.path), title=k.title)

    def _topics(self, conn: Connection, document_id: DocumentId) -> list[DocumentTopicDto]:
        return [
            DocumentTopicDto(
                id=TopicId(r["id"]), name=r["canonical_name"], kind=TopicKind(r["kind"]), salience=float(r["salience"])
            )
            for r in fetch_all(
                conn,
                "SELECT t.id, t.canonical_name, t.kind, dt.salience FROM document_topics dt"
                " JOIN topics t ON t.id = dt.topic_id WHERE dt.document_id = %s"
                " ORDER BY dt.salience DESC, t.canonical_name",
                (document_id,),
            )
        ]

    def _related(
        self, conn: Connection, vault: VaultId, document_id: DocumentId, all_docs: dict[Any, DocKey]
    ) -> list[RelatedDocument]:
        """Semantic links + user-added links, hidden ones excluded; manual first, then score desc."""
        p = {"v": vault, "d": document_id}
        feedback = {
            (r["doc_a"], r["doc_b"]): LinkVerdict(r["verdict"])
            for r in fetch_all(
                conn,
                "SELECT doc_a, doc_b, verdict FROM link_feedback"
                " WHERE vault_id = %(v)s AND (doc_a = %(d)s OR doc_b = %(d)s)",
                p,
            )
        }
        out: list[RelatedDocument] = []
        seen: set[tuple[Any, Any]] = set()
        for r in fetch_all(
            conn,
            "SELECT doc_a, doc_b, score, reason FROM semantic_links"
            " WHERE vault_id = %(v)s AND (doc_a = %(d)s OR doc_b = %(d)s)",
            p,
        ):
            key = (r["doc_a"], r["doc_b"])
            seen.add(key)
            verdict = feedback.get(key)
            other = r["doc_b"] if r["doc_a"] == document_id else r["doc_a"]
            if verdict is LinkVerdict.HIDDEN or other not in all_docs:
                continue
            out.append(
                RelatedDocument(
                    document=self._ref(all_docs[other]), score=float(r["score"]), reason=r["reason"], feedback=verdict
                )
            )
        for key, verdict in feedback.items():
            if verdict is not LinkVerdict.ADDED or key in seen:
                continue
            other = key[1] if key[0] == document_id else key[0]
            if other in all_docs:
                out.append(RelatedDocument(document=self._ref(all_docs[other]), score=None, reason=None, feedback=verdict))
        out.sort(key=lambda r: (r.score is not None, -(r.score or 0.0), r.document.title.lower()))
        return out

    def _outgoing(self, conn: Connection, document_id: DocumentId, resolver: WikiResolver) -> list[OutgoingWikiLinkDto]:
        out: list[OutgoingWikiLinkDto] = []
        for r in fetch_all(
            conn, "SELECT target_name, anchor FROM wiki_links WHERE source_doc_id = %s ORDER BY ordinal", (document_id,)
        ):
            target = resolver.resolve(r["target_name"])
            out.append(
                OutgoingWikiLinkDto(
                    target_name=r["target_name"], anchor=r["anchor"], resolved=self._ref(target) if target else None
                )
            )
        return out

    def _backlinks(
        self,
        conn: Connection,
        vault: VaultId,
        document_id: DocumentId,
        resolver: WikiResolver,
        all_docs: dict[Any, DocKey],
    ) -> list[BacklinkDto]:
        out: list[BacklinkDto] = []
        seen: set[tuple[Any, str | None]] = set()
        for r in fetch_all(
            conn,
            "SELECT w.source_doc_id, w.target_name, w.anchor FROM wiki_links w"
            " JOIN documents d ON d.id = w.source_doc_id"
            " WHERE d.vault_id = %s AND w.source_doc_id <> %s ORDER BY d.path, w.ordinal",
            (vault, document_id),
        ):
            target = resolver.resolve(r["target_name"])
            if target is None or target.id != document_id:
                continue
            key = (r["source_doc_id"], r["anchor"])
            if key in seen or r["source_doc_id"] not in all_docs:
                continue
            seen.add(key)
            out.append(BacklinkDto(document=self._ref(all_docs[r["source_doc_id"]]), anchor=r["anchor"]))
        return out

    def _markdown(self, conn: Connection, vault: VaultId, doc: dict[str, Any]) -> str:
        path = self.roots.file_for(vault, doc.get("root_path"), doc["origin"], doc["path"])
        if path is not None:
            try:
                return strip_frontmatter(path.read_bytes().decode("utf-8", errors="replace"))
            except OSError:
                pass
        rows = fetch_all(conn, "SELECT text FROM chunks WHERE document_id = %s ORDER BY ordinal", (doc["id"],))
        return "\n\n".join(r["text"] for r in rows)
