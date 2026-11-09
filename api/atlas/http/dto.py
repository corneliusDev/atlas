"""HTTP request/response DTOs. JSON shapes are the web client's contract (see web/src/api/openapi.json).

Domain value types that are already JSON-friendly (GraphView, SearchHit, LinkEvidenceView,
ScanReport, IgnoredFile) are reused directly so there is one definition of each shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atlas.types import (
    ClusterId,
    DocumentId,
    DocumentPair,
    FileStatus,
    GraphView,
    IgnoredFile,
    IngestError,
    IndexStage,
    IngestOutcome,
    JobId,
    JobState,
    LinkEvidenceView,
    LinkVerdict,
    ScanReport,
    SearchHit,
    TopicId,
    TopicKind,
    VaultId,
    VaultPath,
)


class Dto(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---- health / vaults ----------------------------------------------------------
class HealthResponse(Dto):
    status: Literal["ok", "degraded"]
    database: bool
    embeddings: bool  # Ollama reachable and model pulled
    llm: Literal["enabled", "embeddings_only"]
    llm_model: str | None
    version: str


class VaultDto(Dto):
    id: VaultId
    name: str
    root_path: str
    mounted: bool  # root_path exists and contains at least one entry
    document_count: int


class VaultListResponse(Dto):
    vaults: list[VaultDto]


# ---- uploads / scan / recluster -----------------------------------------------
# POST /api/uploads is multipart/form-data: files[] (one or more .md/.markdown or .zip) and an
# optional `vault` form field (defaults to DEFAULT_VAULT_ID). Zip entries keep their folder path.
class AcceptedFile(Dto):
    path: VaultPath
    job_id: JobId
    unchanged: bool  # same content hash as stored; job still enqueued, will be Skipped


class UploadResponse(Dto):
    vault: VaultId
    accepted: list[AcceptedFile]
    ignored: list[IgnoredFile]


ScanResponse = ScanReport


class ReclusterResponse(Dto):
    vault: VaultId
    job_id: JobId


# ---- search ----------------------------------------------------------------------
class SearchResponse(Dto):
    query: str
    hits: list[SearchHit]
    took_ms: int


# ---- graph -------------------------------------------------------------------------
GraphResponse = GraphView


# ---- links ---------------------------------------------------------------------------
LinkEvidenceResponse = LinkEvidenceView


class FeedbackRequest(Dto):
    verdict: LinkVerdict


class FeedbackResponse(Dto):
    pair: DocumentPair
    verdict: LinkVerdict
    updated_at: datetime


# ---- documents (DV-1 / DV-2) ------------------------------------------------------------
class DocumentRef(Dto):
    id: DocumentId
    path: VaultPath
    title: str


class RelatedDocument(Dto):
    document: DocumentRef
    score: float | None  # None for manual (ADDED) links
    reason: str | None
    feedback: LinkVerdict | None


class DocumentTopicDto(Dto):
    id: TopicId
    name: str
    kind: TopicKind
    salience: float


class BacklinkDto(Dto):
    document: DocumentRef
    anchor: str | None


class OutgoingWikiLinkDto(Dto):
    target_name: str
    anchor: str | None
    resolved: DocumentRef | None  # None = ghost


class DocumentDetail(Dto):
    id: DocumentId
    vault: VaultId
    path: VaultPath
    origin: Literal["vault", "upload"]
    title: str
    markdown: str  # raw body (frontmatter removed); the client renders it
    frontmatter: dict[str, Any]
    summary: str | None
    tags: list[str]
    cluster_id: ClusterId | None
    indexed_at: datetime
    topics: list[DocumentTopicDto]
    related: list[RelatedDocument]  # semantic + manual, score desc, hidden excluded
    backlinks: list[BacklinkDto]  # incoming [[wikilinks]]
    outgoing: list[OutgoingWikiLinkDto]


# ---- jobs / progress tray (UP-4) -------------------------------------------------------
class FileProgress(Dto):
    job_id: JobId
    path: VaultPath
    kind: Literal["upsert", "remove"]
    status: FileStatus
    attempts: int
    error: IngestError | None
    outcome: IngestOutcome | None
    updated_at: datetime
    stage: IndexStage | None  # set only while status == "indexing", else null
    started_at: datetime | None  # when the current attempt was claimed


class JobFailure(Dto):
    job_id: JobId
    kind: Literal["upsert", "remove", "recluster"]
    path: VaultPath | None
    error: IngestError
    attempts: int
    failed_at: datetime


class JobsStatusResponse(Dto):
    vault: VaultId
    counts: dict[JobState, int]  # every JobState key present, 0 when none
    files: list[FileProgress] = Field(description="Latest job per path, most recently updated first (limit)")
    recent_failures: list[JobFailure]
    recluster_pending: bool
    idle: bool  # no pending or running jobs
    avg_seconds_per_file: float | None = Field(
        description="Mean (finished_at - started_at) over the most recent up to 20 done upsert jobs; null if none"
    )


# ---- errors -------------------------------------------------------------------------------
class ErrorResponse(Dto):
    detail: str
