/**
 * In-memory mock of the Atlas backend. It produces responses shaped exactly like the API DTOs
 * (see src/api/openapi.json), so the UI runs with no backend (VITE_USE_MOCKS=1) and tests can
 * assert against realistic data. Reset between tests with `resetMockDb()`.
 */
import type {
  ClusterInfo,
  DocumentDetail,
  FileProgress,
  FileStatus,
  GraphEdge,
  GraphNode,
  GraphView,
  IgnoredFile,
  JobFailure,
  JobsStatusResponse,
  LinkEvidenceView,
  LinkVerdict,
  NodeKind,
  SearchHit,
  TopicKind,
  UploadResponse,
} from "../api/types";
import {
  CROSS_LINKS,
  DEFAULT_VAULT,
  PALETTE,
  SEED_CLUSTERS,
  SEED_DOCS,
  SEED_TOPICS,
  chunkId,
  clusterId,
  docId,
  topicId,
} from "./data";

export interface MockChunk {
  id: string;
  heading_path: string[];
  text: string;
}

export interface MockDoc {
  id: string;
  path: string;
  title: string;
  origin: "vault" | "upload";
  cluster: string | null;
  tags: string[];
  summary: string | null;
  markdown: string;
  frontmatter: Record<string, unknown>;
  indexedAt: string;
  topics: { id: string; salience: number }[];
  wiki: { target: string; anchor: string | null }[];
  chunks: MockChunk[];
}

export interface MockTopic {
  id: string;
  name: string;
  kind: TopicKind;
}

export interface MockCluster {
  id: string;
  label: string | null;
  color: string;
}

export interface MockLink {
  a: string;
  b: string;
  score: number;
  reason: string | null;
  aChunk: string;
  bChunk: string;
}

interface MockJob {
  job_id: string;
  path: string;
  stage: 0 | 1 | 2 | 3; // queued, indexing, linked, failed
  attempts: number;
  updated_at: string;
  text: string;
  fail: boolean;
  documentId: string | null;
}

interface Db {
  docs: MockDoc[];
  topics: MockTopic[];
  clusters: MockCluster[];
  links: MockLink[];
  feedback: Map<string, { verdict: LinkVerdict; updated_at: string }>;
  jobs: MockJob[];
  jobSeq: number;
  clock: number;
}

let db: Db = seed(false);

const BASE_TIME = Date.parse("2026-11-01T09:00:00Z");

function tick(): string {
  db.clock += 1000;
  return new Date(db.clock).toISOString();
}

function orderPair(x: string, y: string): [string, string] {
  return x < y ? [x, y] : [y, x];
}

export const pairKey = (a: string, b: string) => orderPair(a, b).join(":");

function parseWiki(raw: string): { target: string; anchor: string | null } {
  const [left] = raw.split("|");
  const [target, anchor] = (left ?? raw).split("#");
  return { target: (target ?? raw).trim(), anchor: anchor ? anchor.trim() : null };
}

function makeMarkdown(title: string, summary: string, body: string, wiki: string[], tags: string[]): string {
  const parts = [`# ${title}`, "", summary, "", "## Notes", "", body];
  if (wiki.length) parts.push("", `See also: ${wiki.map((w) => `[[${w}]]`).join(" · ")}`);
  if (tags.length) parts.push("", tags.map((t) => `#${t}`).join(" "));
  return parts.join("\n");
}

function seed(empty: boolean): Db {
  const fresh: Db = {
    docs: [],
    topics: SEED_TOPICS.map((t, i) => ({ id: topicId(i), name: t.name, kind: t.kind })),
    clusters: SEED_CLUSTERS.map((c, i) => ({ id: clusterId(i), label: c.label, color: PALETTE[i % PALETTE.length]! })),
    links: [],
    feedback: new Map(),
    jobs: [],
    jobSeq: 0,
    clock: BASE_TIME,
  };
  if (empty) return fresh;

  const topicByName = new Map(fresh.topics.map((t) => [t.name, t]));
  fresh.docs = SEED_DOCS.map((s, i) => {
    const id = docId(i);
    const topics = s.topics.map(([name, salience]) => ({ id: topicByName.get(name)!.id, salience }));
    for (const tag of s.tags) topics.push({ id: topicByName.get(tag)!.id, salience: 1 });
    return {
      id,
      path: s.path,
      title: s.title,
      origin: "vault",
      cluster: s.cluster === null ? null : clusterId(s.cluster),
      tags: s.tags,
      summary: s.summary,
      markdown: makeMarkdown(s.title, s.summary, s.body, s.wiki, s.tags),
      frontmatter: { tags: s.tags, created: new Date(BASE_TIME - (SEED_DOCS.length - i) * 86_400_000).toISOString().slice(0, 10) },
      indexedAt: new Date(BASE_TIME + i * 60_000).toISOString(),
      topics,
      wiki: s.wiki.map(parseWiki),
      chunks: [
        { id: chunkId(i, 0), heading_path: [s.title], text: s.summary },
        { id: chunkId(i, 1), heading_path: [s.title, "Notes"], text: s.body },
      ],
    } satisfies MockDoc;
  });

  // Semantic links: each doc to the next two in its cluster, plus hand-written cross links.
  const byCluster = new Map<string, MockDoc[]>();
  for (const doc of fresh.docs) {
    if (!doc.cluster) continue;
    byCluster.set(doc.cluster, [...(byCluster.get(doc.cluster) ?? []), doc]);
  }
  let n = 0;
  for (const docs of byCluster.values()) {
    docs.forEach((doc, i) => {
      for (const step of [1, 2]) {
        const other = docs[i + step];
        if (!other) continue;
        n += 1;
        const shared = sharedTopicName(fresh, doc, other);
        const score = Math.round((0.6 + ((n * 37) % 31) / 100) * 1000) / 1000;
        const reason = n % 7 === 0 ? null : shared ? `Both discuss ${shared}.` : "Both cover closely related material.";
        fresh.links.push(makeLink(doc, other, score, reason));
      }
    });
  }
  const byTitle = new Map(fresh.docs.map((d) => [d.title, d]));
  for (const [x, y, score, reason] of CROSS_LINKS) {
    const dx = byTitle.get(x);
    const dy = byTitle.get(y);
    if (dx && dy) fresh.links.push(makeLink(dx, dy, score, reason));
  }
  return fresh;
}

function sharedTopicName(state: Db, x: MockDoc, y: MockDoc): string | null {
  const ys = new Set(y.topics.map((t) => t.id));
  const shared = x.topics
    .filter((t) => ys.has(t.id))
    .map((t) => state.topics.find((tp) => tp.id === t.id)!)
    .sort((p, q) => (p.kind === "tag" ? 1 : 0) - (q.kind === "tag" ? 1 : 0));
  return shared[0]?.name ?? null;
}

function makeLink(x: MockDoc, y: MockDoc, score: number, reason: string | null): MockLink {
  const [a, b] = x.id < y.id ? [x, y] : [y, x];
  return { a: a.id, b: b.id, score, reason, aChunk: a.chunks[a.chunks.length - 1]!.id, bChunk: b.chunks[b.chunks.length - 1]!.id };
}

export function resetMockDb(opts: { empty?: boolean } = {}): void {
  db = seed(opts.empty ?? false);
}

export function mockDbSnapshot(): Readonly<Db> {
  return db;
}

// ---------------------------------------------------------------------------------------------
// Graph
// ---------------------------------------------------------------------------------------------

export interface MockGraphFilters {
  layers: Set<NodeKind>;
  tags: Set<string>;
  clusters: Set<string>;
  origins: Set<string>;
  minScore: number;
  includeHidden: boolean;
  indexedAfter: string | null;
  indexedBefore: string | null;
}

export const ALL_FILTERS: MockGraphFilters = {
  layers: new Set<NodeKind>(["document", "topic", "ghost"]),
  tags: new Set(),
  clusters: new Set(),
  origins: new Set(),
  minScore: 0,
  includeHidden: false,
  indexedAfter: null,
  indexedBefore: null,
};

const docKey = (id: string) => `doc:${id}`;
const topicKey = (id: string) => `topic:${id}`;
const ghostKey = (name: string) => `ghost:${name}`;

function resolveTitle(target: string): MockDoc | undefined {
  const t = target.toLowerCase();
  return db.docs.find((d) => d.title.toLowerCase() === t || d.path.toLowerCase().replace(/\.md$/, "") === t);
}

function docNode(doc: MockDoc): GraphNode {
  return {
    key: docKey(doc.id),
    ref: { kind: "document", id: doc.id },
    label: doc.title,
    path: doc.path,
    summary: doc.summary,
    tags: doc.tags,
    cluster_id: doc.cluster,
    topic_kind: null,
    degree: 0,
    indexed_at: doc.indexedAt,
  };
}

function buildGraph(docs: MockDoc[], f: MockGraphFilters): { nodes: Map<string, GraphNode>; edges: GraphEdge[] } {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  const kept = new Set(docs.map((d) => d.id));
  if (f.layers.has("document")) for (const doc of docs) nodes.set(docKey(doc.id), docNode(doc));

  if (f.layers.has("document")) {
    for (const link of db.links) {
      if (!kept.has(link.a) || !kept.has(link.b) || link.score < f.minScore) continue;
      const fb = db.feedback.get(pairKey(link.a, link.b));
      if (fb?.verdict === "hidden" && !f.includeHidden) continue;
      edges.push({
        key: `semantic:${link.a}:${link.b}`,
        kind: "semantic",
        source: docKey(link.a),
        target: docKey(link.b),
        weight: link.score,
        reason: link.reason,
        anchor: null,
        feedback: fb?.verdict ?? null,
      });
    }
    for (const [key, fb] of db.feedback) {
      if (fb.verdict !== "added") continue;
      const [a, b] = key.split(":") as [string, string];
      if (!kept.has(a) || !kept.has(b)) continue;
      if (db.links.some((l) => l.a === a && l.b === b)) continue;
      edges.push({ key: `manual:${a}:${b}`, kind: "manual", source: docKey(a), target: docKey(b), weight: 1, reason: null, anchor: null, feedback: "added" });
    }
    for (const doc of docs) {
      for (const w of doc.wiki) {
        const resolved = resolveTitle(w.target);
        let target: string;
        if (resolved) {
          if (!kept.has(resolved.id)) continue;
          target = docKey(resolved.id);
        } else {
          if (!f.layers.has("ghost")) continue;
          target = ghostKey(w.target);
          if (!nodes.has(target)) {
            nodes.set(target, { key: target, ref: { kind: "ghost", name: w.target }, label: w.target, path: null, summary: null, tags: [], cluster_id: null, topic_kind: null, degree: 0, indexed_at: null });
          }
        }
        edges.push({ key: `wiki:${doc.id}:${target}`, kind: "wiki", source: docKey(doc.id), target, weight: 1, reason: null, anchor: w.anchor, feedback: null });
      }
      if (f.layers.has("topic")) {
        for (const t of doc.topics) {
          const topic = db.topics.find((tp) => tp.id === t.id)!;
          const key = topicKey(topic.id);
          if (!nodes.has(key)) {
            nodes.set(key, { key, ref: { kind: "topic", id: topic.id }, label: topic.name, path: null, summary: null, tags: [], cluster_id: null, topic_kind: topic.kind, degree: 0, indexed_at: null });
          }
          edges.push({ key: `topic:${doc.id}:${topic.id}`, kind: "topic", source: docKey(doc.id), target: key, weight: t.salience, reason: null, anchor: null, feedback: null });
        }
      }
    }
  }
  // de-duplicate wiki edges (same doc linking twice)
  const seen = new Set<string>();
  const unique = edges.filter((e) => (seen.has(e.key) ? false : (seen.add(e.key), true)));
  for (const e of unique) {
    nodes.get(e.source)!.degree += 1;
    nodes.get(e.target)!.degree += 1;
  }
  return { nodes, edges: unique };
}

function toView(nodes: Map<string, GraphNode>, edges: GraphEdge[], center: string | null): GraphView {
  const list = [...nodes.values()];
  const docsInView = list.filter((n) => n.ref.kind === "document");
  const clusterIds = new Set(docsInView.map((n) => n.cluster_id).filter((c): c is string => !!c));
  const clusters: ClusterInfo[] = db.clusters
    .filter((c) => clusterIds.has(c.id))
    .map((c) => ({ id: c.id, label: c.label, color: c.color, size: db.docs.filter((d) => d.cluster === c.id).length }));
  return {
    nodes: list,
    edges,
    clusters,
    stats: {
      documents: docsInView.length,
      topics: list.filter((n) => n.ref.kind === "topic").length,
      clusters: clusters.length,
      links: edges.filter((e) => e.kind === "semantic" || e.kind === "manual" || (e.kind === "wiki" && e.target.startsWith("doc:"))).length,
    },
    center,
  };
}

export function globalGraph(f: MockGraphFilters): GraphView {
  const docs = db.docs.filter((d) => {
    if (f.clusters.size && !(d.cluster && f.clusters.has(d.cluster))) return false;
    if (f.tags.size && !d.tags.some((t) => f.tags.has(t))) return false;
    if (f.origins.size && !f.origins.has(d.origin)) return false;
    if (f.indexedAfter && d.indexedAt < f.indexedAfter) return false;
    if (f.indexedBefore && d.indexedAt > f.indexedBefore) return false;
    return true;
  });
  const { nodes, edges } = buildGraph(docs, f);
  return toView(nodes, edges, null);
}

export function localGraph(center: string, depth: number): GraphView | null {
  const { nodes: all, edges: allEdges } = buildGraph(db.docs, ALL_FILTERS);
  if (!all.has(center)) return null;
  const adj = new Map<string, string[]>();
  for (const e of allEdges) {
    adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
    adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]);
  }
  const dist = new Map<string, number>([[center, 0]]);
  let frontier = [center];
  for (let level = 1; level <= depth; level++) {
    const next: string[] = [];
    for (const k of frontier) {
      for (const nb of adj.get(k) ?? []) {
        if (!dist.has(nb)) {
          dist.set(nb, level);
          next.push(nb);
        }
      }
    }
    frontier = next;
  }
  const edges = allEdges.filter((e) => dist.has(e.source) && dist.has(e.target));
  const nodes = new Map<string, GraphNode>();
  for (const k of dist.keys()) nodes.set(k, { ...all.get(k)!, degree: 0 });
  for (const e of edges) {
    nodes.get(e.source)!.degree += 1;
    nodes.get(e.target)!.degree += 1;
  }
  return toView(nodes, edges, center);
}

// ---------------------------------------------------------------------------------------------
// Documents, links, feedback
// ---------------------------------------------------------------------------------------------

const ref = (d: MockDoc) => ({ id: d.id, path: d.path, title: d.title });

export function documentDetail(id: string): DocumentDetail | null {
  const doc = db.docs.find((d) => d.id === id);
  if (!doc) return null;
  const related: DocumentDetail["related"] = db.links
    .filter((l) => l.a === id || l.b === id)
    .map((l) => ({ l, other: db.docs.find((d) => d.id === (l.a === id ? l.b : l.a))!, fb: db.feedback.get(pairKey(l.a, l.b)) }))
    .filter((r) => r.fb?.verdict !== "hidden")
    .map((r) => ({ document: ref(r.other), score: r.l.score, reason: r.l.reason, feedback: r.fb?.verdict ?? null }));
  for (const [key, fb] of db.feedback) {
    if (fb.verdict !== "added") continue;
    const [a, b] = key.split(":") as [string, string];
    if (a !== id && b !== id) continue;
    if (db.links.some((l) => l.a === a && l.b === b)) continue;
    const other = db.docs.find((d) => d.id === (a === id ? b : a));
    if (other) related.push({ document: ref(other), score: null, reason: null, feedback: "added" });
  }
  related.sort((x, y) => (y.score ?? 2) - (x.score ?? 2));
  const backlinks = db.docs.flatMap((d) =>
    d.wiki.filter((w) => resolveTitle(w.target)?.id === id).map((w) => ({ document: ref(d), anchor: w.anchor })),
  );
  return {
    id: doc.id,
    vault: DEFAULT_VAULT,
    path: doc.path,
    origin: doc.origin,
    title: doc.title,
    markdown: doc.markdown,
    frontmatter: doc.frontmatter,
    summary: doc.summary,
    tags: doc.tags,
    cluster_id: doc.cluster,
    indexed_at: doc.indexedAt,
    topics: doc.topics
      .map((t) => {
        const topic = db.topics.find((tp) => tp.id === t.id)!;
        return { id: topic.id, name: topic.name, kind: topic.kind, salience: t.salience };
      })
      .filter((t) => t.kind !== "tag")
      .sort((x, y) => y.salience - x.salience),
    related,
    backlinks,
    outgoing: doc.wiki.map((w) => {
      const resolved = resolveTitle(w.target);
      return { target_name: w.target, anchor: w.anchor, resolved: resolved ? ref(resolved) : null };
    }),
  };
}

export function linkEvidence(x: string, y: string): LinkEvidenceView | null {
  const [a, b] = orderPair(x, y);
  const da = db.docs.find((d) => d.id === a);
  const dbb = db.docs.find((d) => d.id === b);
  if (!da || !dbb) return null;
  const link = db.links.find((l) => l.a === a && l.b === b);
  const fb = db.feedback.get(pairKey(a, b));
  if (!link && fb?.verdict !== "added") return null;
  const passage = (doc: MockDoc, chunk: string | undefined) => {
    const c = doc.chunks.find((ch) => ch.id === chunk);
    return c ? { chunk_id: c.id, heading_path: c.heading_path, text: c.text } : null;
  };
  return {
    pair: { a, b },
    a: { document_id: da.id, path: da.path, title: da.title },
    b: { document_id: dbb.id, path: dbb.path, title: dbb.title },
    origin: link ? "semantic" : "manual",
    score: link?.score ?? null,
    reason: link?.reason ?? null,
    a_passage: link ? passage(da, link.aChunk) : null,
    b_passage: link ? passage(dbb, link.bChunk) : null,
    feedback: fb?.verdict ?? null,
  };
}

export function recordFeedback(x: string, y: string, verdict: LinkVerdict) {
  const [a, b] = orderPair(x, y);
  const updated_at = tick();
  db.feedback.set(`${a}:${b}`, { verdict, updated_at });
  return { pair: { a, b }, verdict, updated_at };
}

// ---------------------------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------------------------

export function search(q: string, limit: number, tags: string[], clusters: string[]): SearchHit[] {
  const terms = q.toLowerCase().split(/\s+/).filter((t) => t.length > 1);
  if (!terms.length) return [];
  const scored = db.docs
    .filter((d) => (!tags.length || d.tags.some((t) => tags.includes(t))) && (!clusters.length || (d.cluster !== null && clusters.includes(d.cluster))))
    .map((d) => {
      const title = d.title.toLowerCase();
      const summary = (d.summary ?? "").toLowerCase();
      const body = d.markdown.toLowerCase();
      const topicNames = d.topics.map((t) => db.topics.find((tp) => tp.id === t.id)!.name.toLowerCase()).join(" ");
      let kw = 0;
      let sem = 0;
      for (const t of terms) {
        if (title.includes(t)) kw += 3;
        if (summary.includes(t)) kw += 2;
        if (body.includes(t)) kw += 1;
        if (topicNames.includes(t)) sem += 2;
      }
      return { d, kw, sem, total: kw + sem };
    })
    .filter((s) => s.total > 0)
    .sort((x, y) => y.total - x.total || x.d.title.localeCompare(y.d.title))
    .slice(0, limit);
  const max = scored[0]?.total ?? 1;
  const kwOrder = [...scored].filter((s) => s.kw > 0).sort((x, y) => y.kw - x.kw);
  const semOrder = [...scored].filter((s) => s.sem > 0).sort((x, y) => y.sem - x.sem);
  return scored.map((s) => {
    const chunk = s.d.chunks.find((c) => terms.some((t) => c.text.toLowerCase().includes(t))) ?? s.d.chunks[0]!;
    return {
      node: { kind: "document", id: s.d.id },
      document_id: s.d.id,
      path: s.d.path,
      title: s.d.title,
      chunk_id: chunk.id,
      heading_path: chunk.heading_path,
      snippet: snippetFor(chunk.text, terms),
      score: Math.round((s.total / max) * 1000) / 1000,
      keyword_rank: s.kw > 0 ? kwOrder.indexOf(s) + 1 : null,
      semantic_rank: s.sem > 0 ? semOrder.indexOf(s) + 1 : null,
      cluster_id: s.d.cluster,
    } satisfies SearchHit;
  });
}

function snippetFor(text: string, terms: string[]): string {
  const lower = text.toLowerCase();
  const at = Math.min(...terms.map((t) => lower.indexOf(t)).filter((i) => i >= 0), text.length);
  const start = Math.max(0, at - 60);
  const s = text.slice(start, start + 180);
  return `${start > 0 ? "…" : ""}${s}${start + 180 < text.length ? "…" : ""}`;
}

// ---------------------------------------------------------------------------------------------
// Uploads and the progress tray
// ---------------------------------------------------------------------------------------------

const MAX_BYTES = 5 * 1024 * 1024;

export async function upload(files: File[]): Promise<UploadResponse> {
  const accepted: UploadResponse["accepted"] = [];
  const ignored: IgnoredFile[] = [];
  for (const file of files) {
    const name = file.name;
    const lower = name.toLowerCase();
    if (name.startsWith("/") || name.split("/").includes("..")) {
      ignored.push({ path: name, reason: "invalid_path" });
      continue;
    }
    if (file.size > MAX_BYTES) {
      ignored.push({ path: name, reason: "too_large" });
      continue;
    }
    let entries: { path: string; text: string }[];
    if (lower.endsWith(".md") || lower.endsWith(".markdown")) {
      entries = [{ path: name, text: await readText(file) }];
    } else if (lower.endsWith(".zip")) {
      const base = name.replace(/\.zip$/i, "");
      entries = [{ path: `${base}/README.md`, text: `# ${base}\n\nImported from ${name}.` }];
    } else {
      ignored.push({ path: name, reason: "not_markdown" });
      continue;
    }
    for (const entry of entries) {
      const path = `uploads/${entry.path}`;
      const existing = db.docs.find((d) => d.path === path);
      db.jobSeq += 1;
      const job: MockJob = {
        job_id: `10b00000-0000-4000-8000-${db.jobSeq.toString(16).padStart(12, "0")}`,
        path,
        stage: 0,
        attempts: 0,
        updated_at: tick(),
        text: entry.text,
        fail: /fail/i.test(entry.path),
        documentId: null,
      };
      db.jobs = db.jobs.filter((j) => !(j.path === path && j.stage === 0));
      db.jobs.push(job);
      accepted.push({ path, job_id: job.job_id, unchanged: !!existing && existing.markdown === entry.text });
    }
  }
  return { vault: DEFAULT_VAULT, accepted, ignored };
}

async function readText(file: File): Promise<string> {
  try {
    return await file.text();
  } catch {
    return "";
  }
}

const STAGE_STATUS: FileStatus[] = ["queued", "indexing", "linked", "failed"];

/** Every poll advances each live job one step: queued -> indexing -> linked | failed. */
export function jobsStatus(advance = true): JobsStatusResponse {
  if (advance) {
    for (const job of db.jobs) {
      if (job.stage === 0) {
        job.stage = 1;
        job.attempts += 1;
        job.updated_at = tick();
      } else if (job.stage === 1) {
        job.stage = job.fail ? 3 : 2;
        job.updated_at = tick();
        if (!job.fail) job.documentId = indexUpload(job);
      }
    }
  }
  const files: FileProgress[] = [...db.jobs]
    .sort((x, y) => y.updated_at.localeCompare(x.updated_at))
    .map((j) => ({
      job_id: j.job_id,
      path: j.path,
      kind: "upsert",
      status: STAGE_STATUS[j.stage]!,
      attempts: j.attempts,
      error: j.stage === 3 ? { kind: "model_unavailable", detail: "Ollama is not reachable at http://ollama:11434" } : null,
      outcome:
        j.stage === 2
          ? { kind: "indexed", document_id: j.documentId!, path: j.path, link_count: 2, topic_count: 1, cluster_id: db.docs.find((d) => d.id === j.documentId)?.cluster ?? null }
          : null,
      updated_at: j.updated_at,
    }));
  const failures: JobFailure[] = db.jobs
    .filter((j) => j.stage === 3)
    .map((j) => ({ job_id: j.job_id, kind: "upsert", path: j.path, error: { kind: "model_unavailable", detail: "Ollama is not reachable at http://ollama:11434" }, attempts: j.attempts, failed_at: j.updated_at }));
  const counts = { pending: 0, running: 0, done: 0, failed: 0 };
  for (const j of db.jobs) counts[(["pending", "running", "done", "failed"] as const)[j.stage]] += 1;
  return {
    vault: DEFAULT_VAULT,
    counts,
    files,
    recent_failures: failures,
    recluster_pending: false,
    idle: counts.pending === 0 && counts.running === 0,
  };
}

function indexUpload(job: MockJob): string {
  const i = db.docs.length;
  const id = `d0c10000-0000-4000-8000-${(i + 1).toString(16).padStart(12, "0")}`;
  const body = job.text.replace(/^---[\s\S]*?---\n?/, "");
  const title = body.match(/^#\s+(.+)$/m)?.[1]?.trim() ?? job.path.split("/").pop()!.replace(/\.(md|markdown)$/i, "");
  const firstPara = body.split(/\n\s*\n/).map((p) => p.trim()).find((p) => p && !p.startsWith("#")) ?? null;
  const words = new Set(body.toLowerCase().match(/[a-z]{4,}/g) ?? []);
  const overlap = db.docs
    .map((d) => ({ d, n: (d.markdown.toLowerCase().match(/[a-z]{4,}/g) ?? []).filter((w) => words.has(w)).length }))
    .sort((x, y) => y.n - x.n);
  const cluster = overlap[0]?.d.cluster ?? db.clusters[0]?.id ?? null;
  const doc: MockDoc = {
    id,
    path: job.path,
    title,
    origin: "upload",
    cluster,
    tags: [],
    summary: firstPara,
    markdown: body,
    frontmatter: {},
    indexedAt: job.updated_at,
    topics: [],
    wiki: [...body.matchAll(/\[\[([^\]]+)\]\]/g)].map((m) => parseWiki(m[1]!)),
    chunks: [{ id: `cc100000-0000-4000-8000-${(i + 1).toString(16).padStart(12, "0")}`, heading_path: [title], text: firstPara ?? title }],
  };
  db.docs.push(doc);
  for (const { d } of overlap.slice(0, 2)) db.links.push(makeLink(doc, d, 0.7, "Shares vocabulary with this note."));
  return id;
}
