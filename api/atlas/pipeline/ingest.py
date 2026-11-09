"""The concrete IngestPipeline (implements ``atlas.ports.IngestPipeline``), PRD Output 1.

Every model call (EmbeddingModel, LanguageModel) and every repository read happens before the
single write (``save_document`` / ``delete_document`` / ``replace_clusters``); each job ends in
exactly one write transaction, owned by the repository. Port exceptions
(``ModelUnavailableError`` / ``ModelTimeoutError``) become ``IngestError`` values here and
nowhere else.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Sequence, assert_never

import numpy as np
import numpy.typing as npt

from atlas.pipeline.chunking import chunk
from atlas.pipeline.clustering import cluster, nearest_cluster
from atlas.pipeline.markdown import parse_markdown
from atlas.pipeline.scoring import match_chunks, score_links
from atlas.ports import (
    ClusterRepository,
    DocumentRepository,
    EmbeddingModel,
    FileReader,
    LanguageModel,
    StageReporter,
    no_stage_report,
    ModelTimeoutError,
    ModelUnavailableError,
)
from atlas.types import (
    ClusterAssignment,
    ClusterId,
    ClusterSample,
    ContentHash,
    DocumentAggregate,
    DocumentId,
    DocumentVector,
    EmbeddedChunk,
    EmbeddedTopic,
    Embedding,
    IngestError,
    IngestJob,
    IngestOutcome,
    Indexed,
    LinkEvidence,
    ModelTimeout,
    ModelUnavailable,
    NotUtf8,
    ParsedNote,
    Recluster,
    Reclustered,
    Remove,
    Removed,
    Saved,
    ScoredPair,
    SemanticLink,
    Skipped,
    SkipReason,
    Superseded,
    TopicKind,
    TopicMention,
    Upsert,
    VaultId,
    VaultPath,
    WikiLink,
    chunk_id_for,
    document_id_for,
)

if TYPE_CHECKING:
    from atlas.config import Settings

Origin = Literal["vault", "upload"]


# ---- File access (port: atlas.ports.FileReader) ------------------------------------------------
@dataclass(frozen=True)
class FsFileReader:
    """Reads vault files from ``vault_root`` (read-only mount) and uploads from
    ``<uploads_root>/<vault_id>/<path>``. ``vault_roots`` overrides the vault root per vault."""

    vault_root: Path
    uploads_root: Path
    vault_roots: tuple[tuple[VaultId, Path], ...] = ()

    def _root(self, vault: VaultId, origin: Origin) -> Path:
        if origin == "upload":
            return self.uploads_root / str(vault)
        return dict(self.vault_roots).get(vault, self.vault_root)

    def read(self, vault: VaultId, path: VaultPath, origin: Origin) -> bytes | None:
        root = self._root(vault, origin).resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):  # VaultPath forbids "..", but symlinks could escape
            return None
        try:
            return target.read_bytes()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None


# ---- Configuration ----------------------------------------------------------------------------
@dataclass(frozen=True)
class PipelineConfig:
    link_top_k: int = 8  # SL-1
    link_threshold: float = 0.55
    knn_candidates: int = 24  # nearest_documents k before chunk re-scoring
    topic_merge_threshold: float = 0.88
    chunk_max_tokens: int = 500
    chunk_overlap: int = 50
    # A new doc joins the nearest existing cluster only above this cosine similarity.
    cluster_min_similarity: float = 0.0
    cluster_sample_size: int = 5  # docs per cluster sent to label_clusters

    @classmethod
    def from_settings(cls, settings: Settings) -> PipelineConfig:
        return cls(
            link_top_k=settings.link_top_k,
            link_threshold=settings.link_threshold,
            knn_candidates=settings.knn_candidates,
            topic_merge_threshold=settings.topic_merge_threshold,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def content_hash_of(data: bytes) -> ContentHash:
    """sha256 hex of the raw file bytes (the scanner must hash the same way)."""
    return ContentHash(hashlib.sha256(data).hexdigest())


def _mean_unit(vectors: Sequence[Embedding]) -> Embedding:
    m = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mean = (m / norms).mean(axis=0)
    norm = float(np.linalg.norm(mean)) or 1.0
    return tuple(float(v) for v in mean / norm)


# ---- The pipeline -----------------------------------------------------------------------------
class IngestPipelineImpl:
    """Implements ``atlas.ports.IngestPipeline``. Stateless between jobs; safe to reuse."""

    def __init__(
        self,
        *,
        files: FileReader,
        documents: DocumentRepository,
        clusters: ClusterRepository,
        embeddings: EmbeddingModel,
        language: LanguageModel,
        config: PipelineConfig = PipelineConfig(),
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._files = files
        self._documents = documents
        self._clusters = clusters
        self._embeddings = embeddings
        self._language = language
        self._config = config
        self._clock = clock

    def run(self, job: IngestJob, report: StageReporter = no_stage_report) -> IngestOutcome | IngestError:
        """``report`` is called at the start of each Upsert stage (reading, parsing, embedding,
        enriching, linking, saving); Remove and Recluster report nothing."""
        try:
            match job:
                case Upsert():
                    return self._upsert(job, report)
                case Remove():
                    return self._remove(job.vault, job.path)
                case Recluster():
                    return self._recluster(job.vault)
                case _:
                    assert_never(job)
        except ModelUnavailableError as exc:
            return ModelUnavailable(detail=exc.detail)
        except ModelTimeoutError as exc:
            return ModelTimeout(step=exc.step)

    # -- Remove ---------------------------------------------------------------------------
    def _remove(self, vault: VaultId, path: VaultPath) -> Removed:
        self._documents.delete_document(vault, path)  # ONE tx; no-op when absent
        return Removed(path=path)

    # -- Upsert ---------------------------------------------------------------------------
    def _upsert(self, job: Upsert, report: StageReporter) -> IngestOutcome | IngestError:
        report("reading")
        data = self._files.read(job.vault, job.path, job.origin)
        if data is None:  # vanished between enqueue and run
            return self._remove(job.vault, job.path)
        new_hash = content_hash_of(data)
        stored_hash = self._documents.current_hash(job.vault, job.path)
        if stored_hash == new_hash:
            return Skipped(path=job.path, reason=SkipReason.UNCHANGED)
        try:
            raw = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return NotUtf8(path=job.path)

        report("parsing")
        cfg = self._config
        doc_id = document_id_for(job.vault, job.path)
        note = parse_markdown(job.path, raw).model_copy(update={"content_hash": new_hash})
        chunks = chunk(note, max_tokens=cfg.chunk_max_tokens, overlap=cfg.chunk_overlap)

        # Network (outside any transaction): embeddings, then LLM enrichment.
        report("embedding")
        chunk_vectors = self._embeddings.embed([c.text for c in chunks])
        embedded = tuple(
            EmbeddedChunk(
                id=chunk_id_for(doc_id, c.ordinal),
                ordinal=c.ordinal,
                heading_path=c.heading_path,
                text=c.text,
                embedding=v,
            )
            for c, v in zip(chunks, chunk_vectors, strict=True)
        )
        doc_vector = _mean_unit(chunk_vectors)

        report("enriching")
        summary = self._language.summarize(note)
        mentions = self._language.extract_topics(note)
        topics = self._embed_topics(note, mentions)
        title = self._title(note, summary.title)
        tags = tuple(sorted(set(note.tags) | {t.strip().lstrip("#").lower() for t in summary.tags if t.strip()}))

        # Reads + pure scoring.
        report("linking")
        neighbors = self._documents.nearest_documents(job.vault, doc_vector, cfg.knn_candidates, exclude=job.path)
        scored = score_links(
            match_chunks(embedded, neighbors), cfg.link_threshold, cfg.link_top_k, source=doc_id
        )
        titles = {n.document_id: n.title for n in neighbors}
        semantic_links = self._explain(doc_id, title, scored, titles)
        cluster_id = nearest_cluster(
            doc_vector, self._clusters.centroids(job.vault), min_similarity=cfg.cluster_min_similarity
        )

        aggregate = DocumentAggregate(
            vault=job.vault,
            document_id=doc_id,
            path=job.path,
            origin=job.origin,
            content_hash=new_hash,
            title=title,
            frontmatter=note.frontmatter,
            tags=tags,
            summary=summary.summary.strip() or None,
            doc_embedding=doc_vector,
            chunks=embedded,
            topics=topics,
            topic_merge_threshold=cfg.topic_merge_threshold,
            wiki_links=tuple(
                WikiLink(source=doc_id, target_name=w.target_name, anchor=w.anchor, alias=w.alias) for w in note.wikilinks
            ),
            semantic_links=semantic_links,
            cluster_id=cluster_id,
            indexed_at=self._clock(),
        )
        report("saving")
        result = self._documents.save_document(aggregate, expected_hash=stored_hash)  # ONE tx
        match result:
            case Saved(document_id=saved_id):
                return Indexed(
                    document_id=saved_id,
                    path=job.path,
                    link_count=len(semantic_links),
                    topic_count=len(topics),
                    cluster_id=cluster_id,
                )
            case Superseded():
                return Skipped(path=job.path, reason=SkipReason.SUPERSEDED)
            case _:
                assert_never(result)

    @staticmethod
    def _title(note: ParsedNote, suggested: str) -> str:
        """Frontmatter title > first H1 > LLM-suggested title > file stem (IX-5)."""
        has_explicit = bool(str(note.frontmatter.get("title") or "").strip()) or any(
            h.level == 1 for h in note.headings
        )
        if has_explicit or not suggested.strip():
            return note.title
        return suggested.strip()

    def _embed_topics(self, note: ParsedNote, mentions: Sequence[TopicMention]) -> tuple[EmbeddedTopic, ...]:
        """LLM topics (deduped by lowercased name, highest salience wins) get a name embedding
        for in-transaction merging; note tags become TAG topics (exact-name match, no vector)."""
        by_name: dict[str, TopicMention] = {}
        for m in mentions:
            name = " ".join(m.name.split())
            if not name or m.kind is TopicKind.TAG:
                continue
            key = name.lower()
            prev = by_name.get(key)
            if prev is None or m.salience > prev.salience:
                by_name[key] = m.model_copy(update={"name": name})
        llm_topics = sorted(by_name.values(), key=lambda m: (-m.salience, m.name.lower()))
        vectors = self._embeddings.embed([m.name for m in llm_topics]) if llm_topics else []
        out = [
            EmbeddedTopic(name=m.name, kind=m.kind, salience=m.salience, aliases=m.aliases, embedding=v)
            for m, v in zip(llm_topics, vectors, strict=True)
        ]
        out.extend(EmbeddedTopic(name=t, kind=TopicKind.TAG, salience=1.0) for t in note.tags)
        return tuple(out)

    def _explain(
        self,
        source: DocumentId,
        source_title: str,
        scored: Sequence[ScoredPair],
        titles: dict[DocumentId, str],
    ) -> tuple[SemanticLink, ...]:
        """LLM one-line reasons for the surviving pairs; a missing reason stays None."""
        if not scored:
            return ()
        evidence = [
            LinkEvidence(
                pair=p.pair,
                a_title=source_title if p.pair.a == source else titles.get(p.pair.a, ""),
                b_title=source_title if p.pair.b == source else titles.get(p.pair.b, ""),
                a_passage=p.a_passage,
                b_passage=p.b_passage,
                score=p.score,
            )
            for p in scored
        ]
        reasons = {r.pair: r.reason.strip() for r in self._language.explain_links(evidence)}
        return tuple(
            SemanticLink(pair=p.pair, score=p.score, reason=reasons.get(p.pair) or None, evidence=p.evidence)
            for p in scored
        )

    # -- Recluster -------------------------------------------------------------------------
    def _recluster(self, vault: VaultId) -> Reclustered:
        vectors = self._documents.all_document_vectors(vault)
        assignment = cluster(vectors)
        samples = self._samples(vectors, assignment)
        labels = self._language.label_clusters(samples) if samples else []
        known = {c.cluster_id for c in assignment.centroids}
        labels = [lab for lab in labels if lab.cluster_id in known]
        self._clusters.replace_clusters(vault, assignment, labels)  # ONE tx
        return Reclustered(cluster_count=len(assignment.centroids))

    def _samples(self, vectors: Sequence[DocumentVector], assignment: ClusterAssignment) -> list[ClusterSample]:
        """Per cluster, the members closest to the centroid (cluster_sample_size of them)."""
        by_id = {v.document_id: v for v in vectors}
        members: dict[ClusterId, list[DocumentVector]] = {}
        for m in assignment.members:
            if m.cluster_id is not None and m.document_id in by_id:
                members.setdefault(m.cluster_id, []).append(by_id[m.document_id])
        out: list[ClusterSample] = []
        for c in assignment.centroids:
            docs = members.get(c.cluster_id, [])
            centroid = np.asarray(c.centroid, dtype=np.float64)

            def closeness(v: DocumentVector, centroid: npt.NDArray[np.float64] = centroid) -> tuple[float, str]:
                vec = np.asarray(v.vector, dtype=np.float64)
                norm = float(np.linalg.norm(vec)) or 1.0
                return (-float(vec @ centroid) / norm, str(v.document_id))

            top = sorted(docs, key=closeness)[: self._config.cluster_sample_size]
            out.append(
                ClusterSample(
                    cluster_id=c.cluster_id,
                    titles=tuple(v.title for v in top),
                    summaries=tuple(v.summary for v in top if v.summary),
                )
            )
        return out


__all__ = ["FileReader", "FsFileReader", "IngestPipelineImpl", "PipelineConfig", "content_hash_of"]
