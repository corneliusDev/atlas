/**
 * Friendly aliases over the generated OpenAPI types (schema.d.ts, regenerated with
 * `npm run gen:api` from src/api/openapi.json). Never hand-edit schema.d.ts.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type GraphView = S["GraphView"];
export type GraphNode = S["GraphNode"];
export type GraphEdge = S["GraphEdge"];
export type GraphStats = S["GraphStats"];
export type ClusterInfo = S["ClusterInfo"];
export type NodeKind = S["NodeKind"];
export type TopicKind = S["TopicKind"];
export type LinkVerdict = S["LinkVerdict"];
export type DocumentPair = S["DocumentPair"];

export type SearchResponse = S["SearchResponse"];
export type SearchHit = S["SearchHit"];

export type DocumentDetail = S["DocumentDetail"];
export type DocumentRef = S["DocumentRef"];
export type RelatedDocument = S["RelatedDocument"];
export type DocumentTopicDto = S["DocumentTopicDto"];
export type BacklinkDto = S["BacklinkDto"];
export type OutgoingWikiLinkDto = S["OutgoingWikiLinkDto"];

export type LinkEvidenceView = S["LinkEvidenceView"];
export type Passage = S["Passage"];
export type FeedbackResponse = S["FeedbackResponse"];

export type UploadResponse = S["UploadResponse"];
export type AcceptedFile = S["AcceptedFile"];
export type IgnoredFile = S["IgnoredFile"];

export type JobsStatusResponse = S["JobsStatusResponse"];
export type FileProgress = S["FileProgress"];
/** Pipeline step of a file that is indexing (FileProgress.stage is non-null only while status === "indexing"). */
export type IndexingStage = NonNullable<FileProgress["stage"]>;
export type FileStatus = S["FileStatus"];
export type JobFailure = S["JobFailure"];
export type JobState = S["JobState"];
export type IngestError = S["ModelUnavailable"] | S["ModelTimeout"] | S["NotUtf8"];
export type IngestOutcome = S["Indexed"] | S["Skipped"] | S["Removed"] | S["Reclustered"];

export type HealthResponse = S["HealthResponse"];
export type VaultListResponse = S["VaultListResponse"];
export type ErrorResponse = S["ErrorResponse"];

export type EdgeKind = GraphEdge["kind"];

/** Filters for GET /api/graph (mirrors the route's query params). */
export interface GraphQuery {
  layers?: NodeKind[];
  tags?: string[];
  clusters?: string[];
  origins?: ("vault" | "upload")[];
  minScore?: number;
  indexedAfter?: string;
  indexedBefore?: string;
  includeHidden?: boolean;
  vault?: string;
}
