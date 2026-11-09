/**
 * Typed client for the Atlas API. Every call goes to the relative `/api` base, so the same
 * build works behind nginx (port 3000), the Vite dev proxy, and MSW mocks.
 */
import type {
  DocumentDetail,
  FeedbackResponse,
  GraphQuery,
  GraphView,
  JobsStatusResponse,
  LinkEvidenceView,
  LinkVerdict,
  SearchResponse,
  UploadResponse,
} from "./types";

export const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

type QueryValue = string | number | boolean | undefined | null | readonly (string | number)[];

/** Builds an absolute URL; arrays become repeated params (`tag=a&tag=b`), as FastAPI expects. */
export function apiUrl(path: string, query: Record<string, QueryValue> = {}): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const url = new URL(`${API_BASE}${path}`, origin);
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const v of value) url.searchParams.append(key, String(v));
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText || "request failed";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail !== undefined) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function graphQueryParams(q: GraphQuery): Record<string, QueryValue> {
  return {
    vault: q.vault,
    layer: q.layers,
    tag: q.tags,
    cluster: q.clusters,
    origin: q.origins,
    min_score: q.minScore && q.minScore > 0 ? q.minScore : undefined,
    indexed_after: q.indexedAfter,
    indexed_before: q.indexedBefore,
    include_hidden: q.includeHidden ? true : undefined,
  };
}

export const api = {
  graph(q: GraphQuery = {}, signal?: AbortSignal): Promise<GraphView> {
    return request(apiUrl("/graph", graphQueryParams(q)), { signal });
  },

  localGraph(node: string, depth: 1 | 2 | 3, vault?: string, signal?: AbortSignal): Promise<GraphView> {
    return request(apiUrl(`/graph/local/${encodeURIComponent(node)}`, { depth, vault }), { signal });
  },

  search(
    q: string,
    opts: { limit?: number; tags?: string[]; clusters?: string[]; vault?: string } = {},
    signal?: AbortSignal,
  ): Promise<SearchResponse> {
    return request(
      apiUrl("/search", { q, limit: opts.limit, tag: opts.tags, cluster: opts.clusters, vault: opts.vault }),
      { signal },
    );
  },

  document(id: string, vault?: string, signal?: AbortSignal): Promise<DocumentDetail> {
    return request(apiUrl(`/documents/${id}`, { vault }), { signal });
  },

  linkEvidence(a: string, b: string, vault?: string, signal?: AbortSignal): Promise<LinkEvidenceView> {
    return request(apiUrl(`/links/${a}/${b}`, { vault }), { signal });
  },

  linkFeedback(a: string, b: string, verdict: LinkVerdict, vault?: string): Promise<FeedbackResponse> {
    return request(apiUrl(`/links/${a}/${b}/feedback`, { vault }), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict }),
    });
  },

  upload(files: readonly File[], vault?: string): Promise<UploadResponse> {
    const form = new FormData();
    for (const f of files) form.append("files", f, relativePath(f));
    if (vault) form.append("vault", vault);
    return request(apiUrl("/uploads"), { method: "POST", body: form });
  },

  jobsStatus(vault?: string, signal?: AbortSignal): Promise<JobsStatusResponse> {
    return request(apiUrl("/jobs/status", { vault }), { signal });
  },
};

/** Keeps the folder path for files picked with a directory input (webkitRelativePath). */
function relativePath(f: File): string {
  const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
  return rel && rel.length > 0 ? rel : f.name;
}
