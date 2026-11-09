"""Ports (PRD Output 2): typing.Protocols every adapter implements. No vendor names here.

Exceptions: model ports RAISE ``ModelUnavailableError`` / ``ModelTimeoutError``. Only
``IngestPipeline.run`` turns them into the ``IngestError`` values in ``atlas.types``
(``ModelUnavailable`` / ``ModelTimeout``); the ``Error`` suffix keeps the two apart.
Enrichment failures (bad JSON, refusal, max_tokens) are NOT exceptions: the LanguageModel
adapter returns ``None``-ish results per the PRD ("errors defined out of existence"); see the
per-method notes below.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol, Sequence

from atlas.types import (
    ClaimedJob,
    ClusterAssignment,
    ClusterCentroid,
    ClusterId,
    ClusterLabel,
    ClusterSample,
    ContentHash,
    Depth,
    DocumentAggregate,
    DocumentOrigin,
    DocumentPair,
    DocumentVector,
    Embedding,
    GraphFilters,
    GraphView,
    IngestError,
    IngestJob,
    IngestOutcome,
    JobId,
    LinkEvidence,
    LinkEvidenceView,
    LinkReason,
    LinkVerdict,
    ModelStep,
    Neighbor,
    NodeRef,
    NoteSummary,
    ParsedNote,
    RetryDecision,
    SaveResult,
    ScanReport,
    SearchHit,
    SearchQuery,
    TopicMention,
    VaultId,
    VaultPath,
)

__all__ = [
    "ClusterId",
    "ClusterRepository",
    "DocumentRepository",
    "EmbeddingModel",
    "FileReader",
    "GraphService",
    "IngestPipeline",
    "JobQueue",
    "LanguageModel",
    "LinkFeedbackRepository",
    "ModelPortError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "SearchService",
    "VaultScanner",
]


# ---- Exceptions raised by model ports --------------------------------------
class ModelPortError(Exception):
    """Base for exceptions raised by EmbeddingModel / LanguageModel adapters."""


class ModelUnavailableError(ModelPortError):
    """Service unreachable, 429/5xx after SDK retries, or model not pulled.
    -> IngestError ModelUnavailable(detail=str(exc)) (retryable)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ModelTimeoutError(ModelPortError):
    """Call exceeded the adapter timeout. -> IngestError ModelTimeout(step=exc.step)."""

    def __init__(self, step: ModelStep, detail: str = "") -> None:
        super().__init__(f"{step}: {detail}" if detail else step)
        self.step: ModelStep = step


# ---- Queue and entry points -------------------------------------------------
class JobQueue(Protocol):
    def enqueue(self, job: IngestJob) -> JobId: ...  # replaces a pending job for the same (vault, path)
    def claim(self, lease: timedelta) -> ClaimedJob | None: ...
    def complete(self, job_id: JobId, outcome: IngestOutcome) -> None: ...
    def fail(self, job_id: JobId, error: IngestError) -> RetryDecision: ...


class VaultScanner(Protocol):
    def scan(self, vault: VaultId) -> ScanReport: ...  # enqueues Upsert / Remove for changed paths only


# ---- File access ----------------------------------------------------------------
class FileReader(Protocol):
    """Reads a job's file bytes (vault mount or uploads dir). None when the file does not exist
    (vanished between enqueue and run)."""

    def read(self, vault: VaultId, path: VaultPath, origin: DocumentOrigin) -> bytes | None: ...


# ---- Pipeline (the one deep module) ------------------------------------------
class IngestPipeline(Protocol):
    def run(self, job: IngestJob) -> IngestOutcome | IngestError: ...


# ---- Model ports ---------------------------------------------------------------
class EmbeddingModel(Protocol):
    def embed(self, texts: Sequence[str]) -> list[Embedding]: ...  # raises ModelUnavailableError / ModelTimeoutError


class LanguageModel(Protocol):
    """All methods may raise ModelUnavailableError / ModelTimeoutError.

    Enrichment failures do not raise: ``summarize`` returns a NoteSummary with summary="" when
    the model refused / hit max_tokens / returned bad JSON (the pipeline stores None);
    ``extract_topics`` returns []; ``explain_links`` / ``label_clusters`` omit the failed items
    (results are matched by pair / cluster_id, not by position)."""

    def summarize(self, note: ParsedNote) -> NoteSummary: ...
    def extract_topics(self, note: ParsedNote) -> list[TopicMention]: ...
    def explain_links(self, pairs: Sequence[LinkEvidence]) -> list[LinkReason]: ...
    def label_clusters(self, samples: Sequence[ClusterSample]) -> list[ClusterLabel]: ...


# ---- Repositories (Postgres) -----------------------------------------------------
class DocumentRepository(Protocol):
    def current_hash(self, vault: VaultId, path: VaultPath) -> ContentHash | None: ...
    def nearest_documents(self, vault: VaultId, vector: Embedding, k: int, exclude: VaultPath) -> list[Neighbor]: ...
    def save_document(self, aggregate: DocumentAggregate, expected_hash: ContentHash | None) -> SaveResult: ...
    def delete_document(self, vault: VaultId, path: VaultPath) -> None: ...  # no-op when absent
    def all_document_vectors(self, vault: VaultId) -> list[DocumentVector]: ...
    def stored_hashes(self, vault: VaultId, origin: DocumentOrigin) -> dict[VaultPath, ContentHash]: ...  # VaultScanner diff


class ClusterRepository(Protocol):
    def centroids(self, vault: VaultId) -> list[ClusterCentroid]: ...
    def replace_clusters(self, vault: VaultId, assignment: ClusterAssignment, labels: Sequence[ClusterLabel]) -> None: ...


class LinkFeedbackRepository(Protocol):
    def record(self, vault: VaultId, pair: DocumentPair, verdict: LinkVerdict) -> None: ...  # upsert, idempotent
    # Raises LookupError (store: UnknownDocumentError) when either document is not in the vault -> HTTP 404.


# ---- Read side (api) --------------------------------------------------------------
class SearchService(Protocol):
    def search(self, vault: VaultId, query: SearchQuery) -> list[SearchHit]: ...


class GraphService(Protocol):
    def global_graph(self, vault: VaultId, filters: GraphFilters) -> GraphView: ...
    def local_graph(self, vault: VaultId, center: NodeRef, depth: Depth) -> GraphView: ...
    def link_evidence(self, vault: VaultId, pair: DocumentPair) -> LinkEvidenceView | None: ...
