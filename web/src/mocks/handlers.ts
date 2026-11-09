import { http, HttpResponse, delay } from "msw";
import type { LinkVerdict, NodeKind } from "../api/types";
import { DEFAULT_VAULT } from "./data";
import {
  documentDetail,
  globalGraph,
  jobsStatus,
  linkEvidence,
  localGraph,
  mockDbSnapshot,
  recordFeedback,
  search,
  upload,
} from "./db";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const VERDICTS: LinkVerdict[] = ["confirmed", "hidden", "added"];

/** Small latency in the browser so loading states are visible; none under test. */
const latency = () => (import.meta.env.MODE === "test" ? Promise.resolve() : delay(120));

const notFound = (detail: string) => HttpResponse.json({ detail }, { status: 404 });
const badRequest = (detail: string) => HttpResponse.json({ detail }, { status: 400 });

export const handlers = [
  http.get("*/api/health", () =>
    HttpResponse.json({ status: "ok", database: true, embeddings: true, llm: "enabled", llm_model: "claude-opus-5-5", version: "0.1.0-mock" }),
  ),

  http.get("*/api/vaults", () =>
    HttpResponse.json({
      vaults: [{ id: DEFAULT_VAULT, name: "Default vault", root_path: "/vault", mounted: true, document_count: mockDbSnapshot().docs.length }],
    }),
  ),

  http.get("*/api/graph", async ({ request }) => {
    await latency();
    const p = new URL(request.url).searchParams;
    const layers = p.getAll("layer") as NodeKind[];
    const minScore = Number(p.get("min_score") ?? 0);
    return HttpResponse.json(
      globalGraph({
        layers: new Set<NodeKind>(layers.length ? layers : ["document", "topic", "ghost"]),
        tags: new Set(p.getAll("tag")),
        clusters: new Set(p.getAll("cluster")),
        origins: new Set(p.getAll("origin")),
        minScore: Number.isFinite(minScore) ? minScore : 0,
        includeHidden: p.get("include_hidden") === "true",
        indexedAfter: p.get("indexed_after"),
        indexedBefore: p.get("indexed_before"),
      }),
    );
  }),

  http.get("*/api/graph/local/:node", async ({ params, request }) => {
    await latency();
    const node = decodeURIComponent(String(params.node));
    if (!/^(doc|topic|ghost):.+/.test(node)) return badRequest("invalid node key");
    const depth = Number(new URL(request.url).searchParams.get("depth") ?? 2);
    if (![1, 2, 3].includes(depth)) return badRequest("depth must be 1-3");
    const view = localGraph(node, depth);
    return view ? HttpResponse.json(view) : notFound("node not found");
  }),

  http.get("*/api/search", async ({ request }) => {
    await latency();
    const p = new URL(request.url).searchParams;
    const q = p.get("q") ?? "";
    if (!q.trim()) return badRequest("q is required");
    const started = performance.now();
    const hits = search(q, Number(p.get("limit") ?? 20), p.getAll("tag"), p.getAll("cluster"));
    return HttpResponse.json({ query: q, hits, took_ms: Math.round(performance.now() - started) });
  }),

  http.get("*/api/documents/:id", async ({ params }) => {
    await latency();
    const id = String(params.id);
    if (!UUID.test(id)) return badRequest("invalid document id");
    const doc = documentDetail(id);
    return doc ? HttpResponse.json(doc) : notFound("document not found");
  }),

  http.get("*/api/links/:a/:b", async ({ params }) => {
    await latency();
    const a = String(params.a);
    const b = String(params.b);
    if (a === b) return badRequest("a and b must be different documents");
    const view = linkEvidence(a, b);
    return view ? HttpResponse.json(view) : notFound("no link between these documents");
  }),

  http.put("*/api/links/:a/:b/feedback", async ({ params, request }) => {
    const a = String(params.a);
    const b = String(params.b);
    if (a === b) return badRequest("a and b must be different documents");
    const body = (await request.json()) as { verdict?: LinkVerdict };
    if (!body.verdict || !VERDICTS.includes(body.verdict)) return badRequest("invalid verdict");
    return HttpResponse.json(recordFeedback(a, b, body.verdict));
  }),

  http.post("*/api/uploads", async ({ request }) => {
    // The real api reads, validates and enqueues every file before answering; give the
    // "Processing on server" state a moment to show in the browser demo.
    await (import.meta.env.MODE === "test" ? Promise.resolve() : delay(900));
    const form = await request.formData();
    const files = form.getAll("files").filter((f): f is File => typeof f !== "string");
    if (!files.length) return badRequest("no files");
    return HttpResponse.json(await upload(files));
  }),

  http.get("*/api/jobs/status", () => HttpResponse.json(jobsStatus())),

  http.post("*/api/vaults/:id/scan", ({ params }) =>
    HttpResponse.json({ vault: String(params.id), scanned: mockDbSnapshot().docs.length, upserts: 0, removes: 0, unchanged: mockDbSnapshot().docs.length, ignored: [] }),
  ),

  http.post("*/api/vaults/:id/recluster", ({ params }) =>
    HttpResponse.json({ vault: String(params.id), job_id: "10b00000-0000-4000-8000-ffffffffffff" }),
  ),
];
