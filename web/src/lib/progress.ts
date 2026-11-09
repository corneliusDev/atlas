/**
 * Pure helpers behind the progress feedback: indexing ETA, pipeline stages, tray ordering, upload
 * card wording and the graph layout budget. Kept free of React so they are easy to test.
 */
import type { FileProgress, IgnoredFile, IndexingStage, JobsStatusResponse, UploadResponse } from "../api/types";

/** Files the api indexes in parallel (its worker pool size). Used to turn avg seconds into an ETA. */
export const WORKER_CONCURRENCY = 2;

// ---------------------------------------------------------------------------------------------
// Pipeline stages
// ---------------------------------------------------------------------------------------------

export interface StageInfo {
  stage: IndexingStage;
  /** One-word step label for the compact stepper. */
  short: string;
  /** What the row says while this step runs. */
  long: string;
}

export const STAGES: readonly StageInfo[] = [
  { stage: "reading", short: "Read", long: "Reading file" },
  { stage: "parsing", short: "Parse", long: "Parsing Markdown" },
  { stage: "embedding", short: "Embed", long: "Embedding passages" },
  { stage: "enriching", short: "Summarize", long: "Summarize with Claude" },
  { stage: "linking", short: "Link", long: "Finding links" },
  { stage: "saving", short: "Save", long: "Saving" },
];

/** Index of `stage` in STAGES, or -1 when the backend has not reported one yet. */
export function stageIndex(stage: IndexingStage | null | undefined): number {
  return stage ? STAGES.findIndex((s) => s.stage === stage) : -1;
}

// ---------------------------------------------------------------------------------------------
// ETA
// ---------------------------------------------------------------------------------------------

/**
 * Raw seconds left: avg seconds per file x files left / workers busy on them. Files already
 * running count only for the part of `avg` they have not used yet, so the estimate falls
 * steadily between completions instead of jumping. Null when unknown.
 */
export function rawEtaSeconds(
  status: Pick<JobsStatusResponse, "counts" | "avg_seconds_per_file"> & { files?: readonly FileProgress[] } | null,
  now = Date.now(),
): number | null {
  if (!status) return null;
  const avg = status.avg_seconds_per_file;
  if (avg === null || avg === undefined || !Number.isFinite(avg) || avg <= 0) return null;
  const pending = status.counts.pending ?? 0;
  const running = status.counts.running ?? 0;
  const remaining = pending + running;
  if (remaining <= 0) return null;
  const started = (status.files ?? [])
    .filter((f) => f.status === "indexing" && f.started_at)
    .map((f) => Date.parse(f.started_at!))
    .filter((t) => !Number.isNaN(t))
    .slice(0, running);
  // A file past the average is "almost done", not done: keep a small floor for it.
  const runningLeft = started.reduce((sum, t) => sum + Math.max(avg * 0.15, avg - Math.max(0, now - t) / 1000), 0) + (running - started.length) * avg;
  return (avg * pending + runningLeft) / Math.min(WORKER_CONCURRENCY, remaining);
}

export interface EtaState {
  /** Smoothed seconds left at time `at`. */
  value: number;
  at: number;
}

/**
 * Exponential smoothing that also counts down between polls, so the estimate never jumps around
 * or goes negative. A much larger raw value (a new batch was queued) resets the estimate.
 */
export function smoothEta(prev: EtaState | null, raw: number | null, now: number, alpha = 0.25): EtaState | null {
  if (raw === null || !Number.isFinite(raw)) return null;
  const target = Math.max(0, raw);
  if (!prev) return { value: target, at: now };
  const projected = Math.max(0, prev.value - Math.max(0, now - prev.at) / 1000);
  if (target > projected * 1.75 + 30) return { value: target, at: now };
  return { value: Math.max(0, projected + alpha * (target - projected)), at: now };
}

/** Coarse, calm wording: "a few seconds", "about 40 sec", "about 3 min". Null when there is nothing to say. */
export function formatEta(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 10) return "a few seconds";
  const tens = Math.round(seconds / 10) * 10;
  if (tens < 60) return `about ${tens} sec`;
  if (seconds < 90 * 60) return `about ${Math.max(1, Math.round(seconds / 60))} min`;
  return `about ${Math.round(seconds / 3600)} hr`;
}

/** "8s", "1m 05s": time the current attempt has been running. Clock skew never shows as negative. */
export function formatElapsed(startedAt: string | null | undefined, now: number): string | null {
  if (!startedAt) return null;
  const t = Date.parse(startedAt);
  if (Number.isNaN(t)) return null;
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

// ---------------------------------------------------------------------------------------------
// Tray ordering
// ---------------------------------------------------------------------------------------------

export interface TrayGroups {
  /** Rows always shown: in flight, then failed, recent done, and the next queued files. */
  visible: FileProgress[];
  /** Rows behind "Show more". */
  hidden: FileProgress[];
}

/**
 * Keeps the tray readable with 50+ files. `files` arrive most recently updated first.
 */
export function groupTrayFiles(files: readonly FileProgress[], limits = { failed: 5, done: 5, queued: 3 }): TrayGroups {
  const indexing = files.filter((f) => f.status === "indexing");
  const failed = files.filter((f) => f.status === "failed");
  const done = files.filter((f) => f.status === "linked");
  // Oldest queued first: those are the next to start.
  const queued = files.filter((f) => f.status === "queued").reverse();
  return {
    visible: [...indexing, ...failed.slice(0, limits.failed), ...done.slice(0, limits.done), ...queued.slice(0, limits.queued)],
    hidden: [...failed.slice(limits.failed), ...done.slice(limits.done), ...queued.slice(limits.queued)],
  };
}

// ---------------------------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------------------------

export const plural = (n: number, word: string, many = `${word}s`) => (n === 1 ? word : many);

export const IGNORED_REASON: Record<IgnoredFile["reason"], string> = {
  not_markdown: "not a Markdown file",
  too_large: "larger than 5 MB",
  invalid_path: "invalid path",
};

/** Upload card success line: "3 files uploaded · queued for indexing", "No files uploaded". */
export function uploadSummary(res: UploadResponse): { headline: string; ignored: string | null } {
  const sent = res.accepted.length;
  const unchanged = res.accepted.filter((a) => a.unchanged).length;
  const fresh = sent - unchanged;
  let headline: string;
  if (sent === 0) headline = "No files uploaded";
  else if (fresh === 0) headline = `${sent} ${plural(sent, "file")} uploaded · already up to date`;
  else headline = `${sent} ${plural(sent, "file")} uploaded · queued for indexing`;
  const n = res.ignored.length;
  return { headline, ignored: n ? `${n} ignored` : null };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

// ---------------------------------------------------------------------------------------------
// Graph layout
// ---------------------------------------------------------------------------------------------

/** How long ForceAtlas2 runs before we call the layout settled (ms). */
export function layoutBudgetMs(order: number): number {
  return Math.min(6000, 1500 + order * 6);
}

/** Shorter run when a few nodes join an already-arranged graph (live growth). */
export function incrementalBudgetMs(order: number): number {
  return Math.min(2500, 900 + order * 2);
}

/** 0..1 share of the settle budget used; drives the determinate "Arranging" bar. */
export function layoutProgress(elapsedMs: number, budgetMs: number): number {
  if (budgetMs <= 0) return 1;
  return Math.min(1, Math.max(0, elapsedMs / budgetMs));
}

/**
 * The full "Arranging" overlay is for a fresh layout (first load, or a view that is mostly new);
 * a handful of nodes joining an arranged graph re-settles quietly.
 */
export function isFreshLayout(previousCount: number, newCount: number, total: number): boolean {
  if (total < 2 || newCount === 0) return false;
  return previousCount === 0 || newCount / total > 0.5;
}

/** Iterations for the synchronous layout used when the user prefers reduced motion. */
export function reducedMotionIterations(order: number): number {
  return Math.max(20, Math.min(150, Math.round(60_000 / Math.max(1, order))));
}

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}
