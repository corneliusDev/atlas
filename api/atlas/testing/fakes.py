"""Deterministic in-memory fakes of the ports, for testing pipeline / worker / read logic
without Docker. Not thread-safe. Behaviour mirrors the Postgres contracts closely enough to
test business rules (stale-hash check, one-pending-per-path, retry decisions)."""

from __future__ import annotations

import hashlib
import math
import struct
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable, Sequence

from pydantic import TypeAdapter

from atlas.ports import ModelUnavailableError
from atlas.types import (
    EMBEDDING_DIM,
    CandidateChunk,
    ClaimedJob,
    ClusterAssignment,
    ClusterCentroid,
    ClusterLabel,
    ClusterSample,
    ContentHash,
    DocumentAggregate,
    DocumentOrigin,
    DocumentPair,
    DocumentVector,
    Embedding,
    GaveUp,
    IngestError,
    IngestJob,
    IngestOutcome,
    JobId,
    JobState,
    LinkEvidence,
    LinkReason,
    LinkVerdict,
    Neighbor,
    NoteSummary,
    ParsedNote,
    Recluster,
    RetryAt,
    RetryDecision,
    Saved,
    SaveResult,
    Superseded,
    TopicKind,
    TopicMention,
    VaultId,
    VaultPath,
)

_JOB = TypeAdapter[IngestJob](IngestJob)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def fake_embedding(text: str, dim: int = EMBEDDING_DIM) -> Embedding:
    """sha256-seeded unit vector: same text -> same vector; different texts ~orthogonal."""
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        block = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        for (v,) in struct.iter_unpack(">i", block):
            out.append(v / 2**31)
        counter += 1
    vec = out[:dim]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return tuple(x / norm for x in vec)


# ---- model fakes -------------------------------------------------------------------
@dataclass
class FakeEmbeddingModel:
    """Implements EmbeddingModel. Set ``fail_with`` to make the next calls raise."""

    dim: int = EMBEDDING_DIM
    calls: list[list[str]] = field(default_factory=list)
    fail_with: Exception | None = None

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(list(texts))
        return [fake_embedding(t, self.dim) for t in texts]


@dataclass
class FakeLanguageModel:
    """Implements LanguageModel with canned outputs derived from the input text."""

    calls: list[str] = field(default_factory=list)
    fail_with: Exception | None = None

    def _check(self, name: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(name)

    def summarize(self, note: ParsedNote) -> NoteSummary:
        self._check("summarize")
        words = note.body_text.split()
        first = " ".join(words[:20]) or note.title
        return NoteSummary(
            title=note.title,
            summary=f"{note.title}: {first}. It has {len(words)} words.",
            tags=tuple(sorted({w.lower().strip(".,:;!?") for w in words if len(w) > 9})[:3]),
        )

    def extract_topics(self, note: ParsedNote) -> list[TopicMention]:
        self._check("extract_topics")
        counts: dict[str, int] = {}
        for w in note.body_text.lower().split():
            w = w.strip(".,:;!?()[]\"'`*#")
            if len(w) >= 7 and w.isalpha():
                counts[w] = counts.get(w, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        if not top:
            return []
        mx = top[0][1]
        return [TopicMention(name=w, kind=TopicKind.CONCEPT, salience=round(c / mx, 3)) for w, c in top]

    def explain_links(self, pairs: Sequence[LinkEvidence]) -> list[LinkReason]:
        self._check("explain_links")
        return [LinkReason(pair=p.pair, reason=f"Both discuss {p.a_title} / {p.b_title} themes.") for p in pairs]

    def label_clusters(self, samples: Sequence[ClusterSample]) -> list[ClusterLabel]:
        self._check("label_clusters")
        return [ClusterLabel(cluster_id=s.cluster_id, label=(s.titles[0] if s.titles else "Cluster")[:40]) for s in samples]


# ---- repositories -----------------------------------------------------------------------
@dataclass
class InMemoryDocumentRepository:
    """Implements DocumentRepository. ``docs`` keyed by (vault, path)."""

    docs: dict[tuple[VaultId, VaultPath], DocumentAggregate] = field(default_factory=dict)

    def current_hash(self, vault: VaultId, path: VaultPath) -> ContentHash | None:
        d = self.docs.get((vault, path))
        return d.content_hash if d else None

    def nearest_documents(self, vault: VaultId, vector: Embedding, k: int, exclude: VaultPath) -> list[Neighbor]:
        cands = [d for (v, p), d in self.docs.items() if v == vault and p != exclude]
        scored = sorted(cands, key=lambda d: (-cosine(vector, d.doc_embedding), str(d.document_id)))[:k]
        return [
            Neighbor(
                document_id=d.document_id,
                path=d.path,
                title=d.title,
                doc_score=max(0.0, min(1.0, cosine(vector, d.doc_embedding))),
                chunks=tuple(
                    CandidateChunk(id=c.id, heading_path=c.heading_path, text=c.text, embedding=c.embedding)
                    for c in d.chunks
                ),
            )
            for d in scored
        ]

    def save_document(self, aggregate: DocumentAggregate, expected_hash: ContentHash | None) -> SaveResult:
        key = (aggregate.vault, aggregate.path)
        stored = self.current_hash(*key)
        if stored != expected_hash and stored is not None:
            return Superseded(stored_hash=stored)
        self.docs[key] = aggregate
        return Saved(document_id=aggregate.document_id)

    def delete_document(self, vault: VaultId, path: VaultPath) -> None:
        self.docs.pop((vault, path), None)

    def stored_hashes(self, vault: VaultId, origin: DocumentOrigin) -> dict[VaultPath, ContentHash]:
        return {p: d.content_hash for (v, p), d in self.docs.items() if v == vault and d.origin == origin}

    def all_document_vectors(self, vault: VaultId) -> list[DocumentVector]:
        return [
            DocumentVector(document_id=d.document_id, path=d.path, title=d.title, summary=d.summary, vector=d.doc_embedding)
            for (v, _), d in sorted(self.docs.items(), key=lambda kv: str(kv[1].document_id))
            if v == vault
        ]


@dataclass
class InMemoryClusterRepository:
    """Implements ClusterRepository."""

    assignments: dict[VaultId, ClusterAssignment] = field(default_factory=dict)
    labels: dict[VaultId, tuple[ClusterLabel, ...]] = field(default_factory=dict)

    def centroids(self, vault: VaultId) -> list[ClusterCentroid]:
        a = self.assignments.get(vault)
        return list(a.centroids) if a else []

    def replace_clusters(self, vault: VaultId, assignment: ClusterAssignment, labels: Sequence[ClusterLabel]) -> None:
        self.assignments[vault] = assignment
        self.labels[vault] = tuple(labels)


@dataclass
class InMemoryLinkFeedbackRepository:
    """Implements LinkFeedbackRepository."""

    verdicts: dict[tuple[VaultId, DocumentPair], LinkVerdict] = field(default_factory=dict)

    def record(self, vault: VaultId, pair: DocumentPair, verdict: LinkVerdict) -> None:
        self.verdicts[(vault, pair)] = verdict


# ---- queue -------------------------------------------------------------------------------
@dataclass
class _JobRow:
    id: JobId
    job: IngestJob
    state: JobState
    attempts: int = 0
    run_after: datetime = field(default_factory=lambda: datetime.now(UTC))
    lease_until: datetime | None = None
    outcome: IngestOutcome | None = None
    error: IngestError | None = None


def _dedup_key(job: IngestJob) -> str:
    return "__recluster__" if isinstance(job, Recluster) else job.path


@dataclass
class InMemoryJobQueue:
    """Implements JobQueue with the same rules as the Postgres queue:
    one pending + one running per (vault, dedup_key); enqueue replaces the pending payload;
    claim skips keys with a live running job; fail -> RetryAt(backoff) until max_attempts."""

    max_attempts: int = 3
    base_backoff: timedelta = timedelta(seconds=10)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    rows: list[_JobRow] = field(default_factory=list)

    def _key(self, row: _JobRow) -> tuple[VaultId, str]:
        return (row.job.vault, _dedup_key(row.job))

    def enqueue(self, job: IngestJob) -> JobId:
        job = _JOB.validate_python(job)  # round-trips like the jsonb payload would
        key = (job.vault, _dedup_key(job))
        for row in self.rows:
            if row.state is JobState.PENDING and self._key(row) == key:
                row.job, row.attempts, row.run_after = job, 0, self.clock()
                return row.id
        row = _JobRow(id=JobId(uuid.uuid4()), job=job, state=JobState.PENDING, run_after=self.clock())
        self.rows.append(row)
        return row.id

    def claim(self, lease: timedelta) -> ClaimedJob | None:
        now = self.clock()
        running = {self._key(r) for r in self.rows if r.state is JobState.RUNNING and r.lease_until and r.lease_until > now}
        for row in self.rows:
            if row.state is JobState.RUNNING and row.lease_until and row.lease_until <= now:
                row.state = JobState.PENDING  # expired lease: reclaimable
        for row in self.rows:
            if row.state is JobState.PENDING and row.run_after <= now and self._key(row) not in running:
                row.state, row.attempts, row.lease_until = JobState.RUNNING, row.attempts + 1, now + lease
                return ClaimedJob(job_id=row.id, job=row.job, attempt=row.attempts, lease_until=row.lease_until)
        return None

    def _row(self, job_id: JobId) -> _JobRow:
        for row in self.rows:
            if row.id == job_id:
                return row
        raise KeyError(job_id)

    def complete(self, job_id: JobId, outcome: IngestOutcome) -> None:
        row = self._row(job_id)
        row.state, row.outcome, row.lease_until = JobState.DONE, outcome, None

    def fail(self, job_id: JobId, error: IngestError) -> RetryDecision:
        row = self._row(job_id)
        row.error, row.lease_until = error, None
        if not type(error).retryable or row.attempts >= self.max_attempts:
            row.state = JobState.FAILED
            return GaveUp(attempts=row.attempts)
        at = self.clock() + self.base_backoff * (2 ** row.attempts)
        row.state, row.run_after = JobState.PENDING, at
        return RetryAt(at=at, attempt=row.attempts)

    # test helpers
    def counts(self) -> dict[JobState, int]:
        out = {s: 0 for s in JobState}
        for r in self.rows:
            out[r.state] += 1
        return out


__all__ = [
    "FakeEmbeddingModel",
    "FakeLanguageModel",
    "InMemoryClusterRepository",
    "InMemoryDocumentRepository",
    "InMemoryJobQueue",
    "InMemoryLinkFeedbackRepository",
    "ModelUnavailableError",
    "cosine",
    "fake_embedding",
]
