"""Atlas domain types: NewTypes, closed unions (PRD Output 3) and value types (PRD Output 2).

Conventions
- Every value type is a frozen Pydantic model (``Frozen``). Closed unions use a ``kind``
  Literal discriminator; dispatch with an exhaustive ``match`` + ``assert_never``.
- IDs are ``NewType``s over ``UUID`` so a ``DocumentId`` cannot be passed as a ``VaultId``.
- ``DocumentId`` and ``ChunkId`` are deterministic (uuid5) so the pipeline knows a document's
  id before ``save_document`` and re-indexing a path keeps its id (see ``document_id_for``).
- Collections inside value types are tuples / frozensets so models stay hashable and immutable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any, ClassVar, Literal, NewType, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# NewTypes (Output 2)
# ---------------------------------------------------------------------------

VaultId = NewType("VaultId", UUID)
DocumentId = NewType("DocumentId", UUID)
ClusterId = NewType("ClusterId", UUID)
JobId = NewType("JobId", UUID)
ChunkId = NewType("ChunkId", UUID)
TopicId = NewType("TopicId", UUID)
VaultPath = NewType("VaultPath", str)  # POSIX path relative to vault root: "notes/ideas.md"
ContentHash = NewType("ContentHash", str)  # sha256 hex of the file bytes
Embedding = tuple[float, ...]  # 768-d
Depth = Literal[1, 2, 3]

EMBEDDING_DIM = 768
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})

# The seeded default vault (migration 0001 inserts it, root_path=/vault).
DEFAULT_VAULT_ID = VaultId(UUID("00000000-0000-0000-0000-000000000001"))

# Namespace for deterministic ids. Never change it: ids are persisted.
_ATLAS_NS = UUID("5b1f3c1e-7a8e-4c55-9f0e-6a7d2b9c4e10")


def document_id_for(vault: VaultId, path: VaultPath) -> DocumentId:
    """Deterministic document id: same (vault, path) -> same id across re-indexes."""
    return DocumentId(uuid.uuid5(_ATLAS_NS, f"doc:{vault}:{path}"))


def chunk_id_for(document: DocumentId, ordinal: int) -> ChunkId:
    """Deterministic chunk id: same (document, ordinal) -> same id across re-indexes."""
    return ChunkId(uuid.uuid5(_ATLAS_NS, f"chunk:{document}:{ordinal}"))


def parse_vault_path(raw: str) -> VaultPath | None:
    """The ONLY constructor of ``VaultPath`` from untrusted input.

    Accepts a relative POSIX path ending in .md / .markdown (case-insensitive). Normalises
    backslashes and leading "./". Rejects absolute paths, "..", empty segments, hidden
    files/dirs (".obsidian/...", ".trash/...") and anything else. Returns None when rejected.
    """
    s = raw.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s or s.startswith("/") or "\x00" in s:
        return None
    parts = s.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return None
    p = PurePosixPath(s)
    if p.suffix.lower() not in MARKDOWN_SUFFIXES or p.stem == "":
        return None
    return VaultPath(str(p))


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Small enums
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    DOCUMENT = "document"
    TOPIC = "topic"
    GHOST = "ghost"


class TopicKind(StrEnum):
    CONCEPT = "concept"
    PERSON = "person"
    ORG = "org"
    TAG = "tag"  # frontmatter tags: / inline #tags (SL-5); matched by exact name only


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class FileStatus(StrEnum):
    """UP-4 per-file status, derived from the job row (pending->queued, running->indexing,
    done->linked, failed->failed)."""

    QUEUED = "queued"
    INDEXING = "indexing"
    LINKED = "linked"
    FAILED = "failed"


DocumentOrigin = Literal["vault", "upload"]

# ---------------------------------------------------------------------------
# IngestJob (Output 3)
# ---------------------------------------------------------------------------


class JobBase(Frozen):
    vault: VaultId  # lifted: every job targets one vault


class FileJob(JobBase):
    path: VaultPath  # lifted: only file jobs carry a path


class Upsert(FileJob):
    kind: Literal["upsert"] = "upsert"
    origin: Literal["vault", "upload"]  # which root to read the path from


class Remove(FileJob):
    kind: Literal["remove"] = "remove"


class Recluster(JobBase):
    kind: Literal["recluster"] = "recluster"


IngestJob = Annotated[Upsert | Remove | Recluster, Field(discriminator="kind")]

# ---------------------------------------------------------------------------
# IngestOutcome (Output 3)
# ---------------------------------------------------------------------------


class SkipReason(StrEnum):
    UNCHANGED = "unchanged"  # same content hash as stored
    SUPERSEDED = "superseded"  # file changed while this job ran


class Indexed(Frozen):
    kind: Literal["indexed"] = "indexed"
    document_id: DocumentId
    path: VaultPath
    link_count: int
    topic_count: int
    cluster_id: ClusterId | None  # None until the first Recluster creates clusters


class Skipped(Frozen):
    kind: Literal["skipped"] = "skipped"
    path: VaultPath
    reason: SkipReason


class Removed(Frozen):
    kind: Literal["removed"] = "removed"
    path: VaultPath  # also returned when the doc was already gone


class Reclustered(Frozen):
    kind: Literal["reclustered"] = "reclustered"
    cluster_count: int


IngestOutcome = Annotated[Indexed | Skipped | Removed | Reclustered, Field(discriminator="kind")]

# ---------------------------------------------------------------------------
# IngestError (Output 3). VALUES, not exceptions. The exceptions ports raise are
# atlas.ports.ModelUnavailableError / ModelTimeoutError; IngestPipeline.run converts them.
# ---------------------------------------------------------------------------

ModelStep = Literal["embed", "summarize", "topics", "explain_links", "label_clusters"]


class ModelUnavailable(Frozen):
    kind: Literal["model_unavailable"] = "model_unavailable"
    retryable: ClassVar[bool] = True
    detail: str


class ModelTimeout(Frozen):
    kind: Literal["model_timeout"] = "model_timeout"
    retryable: ClassVar[bool] = True
    step: ModelStep


class NotUtf8(Frozen):
    kind: Literal["not_utf8"] = "not_utf8"
    retryable: ClassVar[bool] = False
    path: VaultPath


IngestError = Annotated[ModelUnavailable | ModelTimeout | NotUtf8, Field(discriminator="kind")]

# ---------------------------------------------------------------------------
# Persistence and queue results (Output 3)
# ---------------------------------------------------------------------------


class Saved(Frozen):
    kind: Literal["saved"] = "saved"
    document_id: DocumentId


class Superseded(Frozen):
    kind: Literal["superseded"] = "superseded"
    stored_hash: ContentHash


SaveResult = Saved | Superseded


class RetryAt(Frozen):
    kind: Literal["retry_at"] = "retry_at"
    at: datetime
    attempt: int


class GaveUp(Frozen):
    kind: Literal["gave_up"] = "gave_up"
    attempts: int


RetryDecision = RetryAt | GaveUp

# ---------------------------------------------------------------------------
# Pairs
# ---------------------------------------------------------------------------


class DocumentPair(Frozen):
    """Ordered pair of distinct documents: ``a < b`` (UUID ordering). Build with ``of``."""

    a: DocumentId
    b: DocumentId

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.a < self.b:
            raise ValueError("DocumentPair requires a < b (use DocumentPair.of)")
        return self

    @classmethod
    def of(cls, x: DocumentId, y: DocumentId) -> DocumentPair:
        if x == y:
            raise ValueError("DocumentPair requires two distinct documents")
        return cls(a=x, b=y) if x < y else cls(a=y, b=x)

    def other(self, doc: DocumentId) -> DocumentId:
        return self.b if doc == self.a else self.a


# ---------------------------------------------------------------------------
# Graph: links and nodes (Output 3)
# ---------------------------------------------------------------------------


class SemanticLink(Frozen):
    kind: Literal["semantic"] = "semantic"
    pair: DocumentPair  # ordered, so one row per pair
    score: float  # cosine similarity, 0-1
    reason: str | None  # None until the LLM explains it
    evidence: tuple[ChunkId, ChunkId]  # (chunk of pair.a, chunk of pair.b)


class WikiLink(Frozen):
    kind: Literal["wiki"] = "wiki"
    source: DocumentId
    target_name: str  # resolved at read time; may stay unresolved
    anchor: str | None  # [[Note#Heading]]


Link = Annotated[SemanticLink | WikiLink, Field(discriminator="kind")]


class DocumentNode(Frozen):
    kind: Literal["document"] = "document"
    id: DocumentId


class TopicNode(Frozen):
    kind: Literal["topic"] = "topic"
    id: TopicId


class GhostNode(Frozen):
    kind: Literal["ghost"] = "ghost"
    name: str  # a [[wikilink]] with no matching note


NodeRef = Annotated[DocumentNode | TopicNode | GhostNode, Field(discriminator="kind")]


def node_key(ref: DocumentNode | TopicNode | GhostNode) -> str:
    """Stable string key used as graph node id and in /api/graph/local/{node}.
    "doc:<uuid>" | "topic:<uuid>" | "ghost:<normalised name>"."""
    match ref:
        case DocumentNode(id=i):
            return f"doc:{i}"
        case TopicNode(id=i):
            return f"topic:{i}"
        case GhostNode(name=n):
            return f"ghost:{n}"


def parse_node_key(key: str) -> DocumentNode | TopicNode | GhostNode | None:
    prefix, sep, rest = key.partition(":")
    if not sep or not rest:
        return None
    try:
        if prefix == "doc":
            return DocumentNode(id=DocumentId(UUID(rest)))
        if prefix == "topic":
            return TopicNode(id=TopicId(UUID(rest)))
    except ValueError:
        return None
    if prefix == "ghost":
        return GhostNode(name=rest)
    return None


class LinkVerdict(StrEnum):
    CONFIRMED = "confirmed"
    HIDDEN = "hidden"
    ADDED = "added"  # user-drawn link between two docs


# ---------------------------------------------------------------------------
# Parsing and chunking (pure pipeline values)
# ---------------------------------------------------------------------------


class WikiLinkRef(Frozen):
    """A [[wikilink]] as written. ``[[Note|alias]]`` -> target_name="Note", alias="alias";
    ``[[Note#Heading]]`` -> anchor="Heading". target_name excludes the .md suffix."""

    target_name: str
    anchor: str | None = None
    alias: str | None = None


class Heading(Frozen):
    level: int = Field(ge=1, le=6)
    text: str
    line: int  # 0-based line in the body (after frontmatter)


class ParsedNote(Frozen):
    path: VaultPath
    title: str  # frontmatter title > first H1 > file stem
    frontmatter: dict[str, Any]  # JSON-compatible values only (dates stringified)
    tags: tuple[str, ...]  # frontmatter tags: + inline #tags; lowercased, no '#', deduped, sorted
    wikilinks: tuple[WikiLinkRef, ...]  # in document order, deduped on (target, anchor)
    headings: tuple[Heading, ...]
    body: str  # markdown after frontmatter (rendering / chunking source)
    body_text: str  # text for embedding: code blocks, images, html comments stripped
    content_hash: ContentHash  # sha256 hex of the raw file bytes


class Chunk(Frozen):
    ordinal: int  # 0-based, document order
    heading_path: tuple[str, ...]  # e.g. ("Pricing", "Tiers")
    text: str


class EmbeddedChunk(Frozen):
    id: ChunkId  # chunk_id_for(document_id, ordinal)
    ordinal: int
    heading_path: tuple[str, ...]
    text: str
    embedding: Embedding


# ---------------------------------------------------------------------------
# Linking values
# ---------------------------------------------------------------------------


class CandidateChunk(Frozen):
    """A chunk of a neighbour document, returned by nearest_documents for re-scoring."""

    id: ChunkId
    heading_path: tuple[str, ...]
    text: str
    embedding: Embedding


class ChunkMatch(Frozen):
    source_chunk: ChunkId  # chunk of the document being indexed
    target_chunk: ChunkId  # chunk of the neighbour
    score: float  # cosine similarity
    source_text: str
    target_text: str


class Neighbor(Frozen):
    """A KNN candidate for the document being indexed.

    ``nearest_documents`` fills doc fields + ``chunks`` (best_match=None). The pipeline's pure
    ``match_chunks`` fills ``best_match``; ``score_links`` then combines doc_score and
    best_match.score."""

    document_id: DocumentId
    path: VaultPath
    title: str
    doc_score: float  # cosine similarity of doc vectors, 0-1
    chunks: tuple[CandidateChunk, ...] = ()
    best_match: ChunkMatch | None = None


class ScoredPair(Frozen):
    """A link that survived threshold + top-k. ``evidence`` is ordered like ``pair``
    (chunk of pair.a, chunk of pair.b)."""

    pair: DocumentPair
    neighbor: DocumentId
    score: float  # combined score, 0-1
    evidence: tuple[ChunkId, ChunkId]
    a_passage: str
    b_passage: str


class LinkEvidence(Frozen):
    """Input to LanguageModel.explain_links: both sides aligned with ``pair``."""

    pair: DocumentPair
    a_title: str
    b_title: str
    a_passage: str
    b_passage: str
    score: float


class LinkReason(Frozen):
    pair: DocumentPair
    reason: str  # one line, <= ~140 chars


# ---------------------------------------------------------------------------
# Language model values
# ---------------------------------------------------------------------------


class NoteSummary(Frozen):
    title: str  # suggested title (used when the note has no frontmatter title / H1)
    summary: str  # two sentences (IX-5)
    tags: tuple[str, ...] = ()  # suggested tags, lowercased


class TopicMention(Frozen):
    name: str  # as the LLM names it, e.g. "machine learning"
    kind: TopicKind  # concept | person | org (TAG is never produced by the LLM)
    salience: float = Field(ge=0.0, le=1.0)
    aliases: tuple[str, ...] = ()  # e.g. ("ML",)


class EmbeddedTopic(Frozen):
    """A topic ready to persist. ``embedding`` is None for TAG topics (exact-name match only)."""

    name: str
    kind: TopicKind
    salience: float = Field(ge=0.0, le=1.0)
    aliases: tuple[str, ...] = ()
    embedding: Embedding | None = None


# ---------------------------------------------------------------------------
# Clustering values
# ---------------------------------------------------------------------------


class DocumentVector(Frozen):
    document_id: DocumentId
    path: VaultPath
    title: str
    summary: str | None
    vector: Embedding


class ClusterCentroid(Frozen):
    cluster_id: ClusterId
    centroid: Embedding
    color: str  # "#rrggbb", assigned by cluster() from a fixed palette


class DocumentCluster(Frozen):
    document_id: DocumentId
    cluster_id: ClusterId | None  # None = noise / unclustered


class ClusterAssignment(Frozen):
    centroids: tuple[ClusterCentroid, ...]
    members: tuple[DocumentCluster, ...]


class ClusterSample(Frozen):
    """Representative docs of one cluster, sent to label_clusters."""

    cluster_id: ClusterId
    titles: tuple[str, ...]
    summaries: tuple[str, ...]


class ClusterLabel(Frozen):
    cluster_id: ClusterId
    label: str  # 1-4 words


# ---------------------------------------------------------------------------
# Aggregate written by save_document (ONE transaction)
# ---------------------------------------------------------------------------


class DocumentAggregate(Frozen):
    """Everything save_document writes for one document in one transaction: the document row,
    its chunks (replaced), its topic edges (replaced; topics resolved/merged in-tx by name,
    alias, or embedding similarity >= topic_merge_threshold), its wiki links (replaced), every
    semantic link involving it (replaced) and its cluster_id."""

    vault: VaultId
    document_id: DocumentId  # == document_id_for(vault, path)
    path: VaultPath
    origin: DocumentOrigin
    content_hash: ContentHash
    title: str
    frontmatter: dict[str, Any]
    tags: tuple[str, ...]
    summary: str | None  # None when the LLM failed/refused or embeddings-only mode
    doc_embedding: Embedding
    chunks: tuple[EmbeddedChunk, ...]
    topics: tuple[EmbeddedTopic, ...]
    topic_merge_threshold: float = 0.88
    wiki_links: tuple[WikiLink, ...]
    semantic_links: tuple[SemanticLink, ...]
    cluster_id: ClusterId | None
    indexed_at: datetime


# ---------------------------------------------------------------------------
# Queue / scanner values
# ---------------------------------------------------------------------------


class ClaimedJob(Frozen):
    job_id: JobId
    job: IngestJob
    attempt: int  # 1 on first claim
    lease_until: datetime


IgnoreReason = Literal["not_markdown", "too_large", "invalid_path"]


class IgnoredFile(Frozen):
    path: str  # raw relative path (not a VaultPath: it was rejected)
    reason: IgnoreReason


class ScanReport(Frozen):
    vault: VaultId
    scanned: int  # markdown files seen
    upserts: int  # Upsert jobs enqueued (new or changed hash)
    removes: int  # Remove jobs enqueued (stored vault-origin doc no longer on disk)
    unchanged: int
    ignored: tuple[IgnoredFile, ...]


# ---------------------------------------------------------------------------
# Read side values
# ---------------------------------------------------------------------------


class SearchQuery(Frozen):
    text: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
    tags: frozenset[str] = frozenset()
    cluster_ids: frozenset[ClusterId] = frozenset()


class SearchHit(Frozen):
    node: DocumentNode
    document_id: DocumentId
    path: VaultPath
    title: str
    chunk_id: ChunkId | None  # best matching passage
    heading_path: tuple[str, ...]
    snippet: str  # plain text; matched terms wrapped in <mark></mark>
    score: float  # fused (RRF) score, higher is better
    keyword_rank: int | None  # 1-based rank in keyword results, None if absent
    semantic_rank: int | None  # 1-based rank in vector results, None if absent
    cluster_id: ClusterId | None


class GraphFilters(Frozen):
    layers: frozenset[NodeKind] = frozenset({NodeKind.DOCUMENT, NodeKind.TOPIC, NodeKind.GHOST})
    tags: frozenset[str] = frozenset()  # empty = all
    cluster_ids: frozenset[ClusterId] = frozenset()  # empty = all
    origins: frozenset[Literal["vault", "upload"]] = frozenset()  # "file type"; empty = all
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)  # semantic edge threshold
    indexed_after: datetime | None = None
    indexed_before: datetime | None = None
    include_hidden: bool = False  # show links the user hid (rendered dimmed)


EdgeKind = Literal["semantic", "wiki", "topic", "manual"]


class GraphNode(Frozen):
    key: str  # node_key(ref)
    ref: NodeRef
    label: str  # title / canonical topic name / ghost name
    path: VaultPath | None = None  # documents only
    summary: str | None = None
    tags: tuple[str, ...] = ()
    cluster_id: ClusterId | None = None
    topic_kind: TopicKind | None = None  # topics only
    degree: int = 0  # for node size (GR-2)
    indexed_at: datetime | None = None


class GraphEdge(Frozen):
    key: str  # e.g. "semantic:<a>:<b>", "wiki:<src>:<target key>", "topic:<doc>:<topic>"
    kind: EdgeKind
    source: str  # node key
    target: str  # node key
    weight: float  # semantic score / topic salience / 1.0 for wiki & manual
    reason: str | None = None
    anchor: str | None = None  # wiki edges with [[Note#Heading]]
    feedback: LinkVerdict | None = None


class ClusterInfo(Frozen):
    id: ClusterId
    label: str | None
    color: str
    size: int


class GraphStats(Frozen):
    documents: int
    topics: int
    clusters: int
    links: int  # semantic + resolved wiki + manual edges


class GraphView(Frozen):
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    clusters: tuple[ClusterInfo, ...]
    stats: GraphStats
    center: str | None = None  # node key for local graphs


class Passage(Frozen):
    chunk_id: ChunkId
    heading_path: tuple[str, ...]
    text: str


class LinkEndpoint(Frozen):
    document_id: DocumentId
    path: VaultPath
    title: str


class LinkEvidenceView(Frozen):
    pair: DocumentPair
    a: LinkEndpoint
    b: LinkEndpoint
    origin: Literal["semantic", "manual"]  # manual = user-added (LinkVerdict.ADDED), no score
    score: float | None
    reason: str | None
    a_passage: Passage | None
    b_passage: Passage | None
    feedback: LinkVerdict | None
