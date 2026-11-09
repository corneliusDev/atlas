import { useEffect, useRef, useState } from "react";
import type { ClusterInfo, FileProgress, FileStatus, GraphStats, IgnoredFile, IngestError, JobsStatusResponse } from "../api/types";
import {
  IGNORED_REASON,
  STAGES,
  formatElapsed,
  formatEta,
  groupTrayFiles,
  plural,
  rawEtaSeconds,
  smoothEta,
  stageIndex,
  type EtaState,
} from "../lib/progress";
import { StageStepper } from "./StageStepper";

interface Props {
  status: JobsStatusResponse | null;
  /** Files the last upload skipped (UP-3). */
  ignored: IgnoredFile[];
  /** Set once a batch finishes: "40 documents, 6 themes, 112 connections". */
  summary: { stats: GraphStats; topClusters: ClusterInfo[] } | null;
  onDismiss: () => void;
  onOpenDocument: (id: string, label: string) => void;
  onZoomCluster: (clusterId: string) => void;
}

const STATUS_LABEL: Record<FileStatus, string> = {
  queued: "Queued",
  indexing: "Indexing",
  linked: "Linked",
  failed: "Failed",
};

/** Human reason for a failed file (UP-4 "failed (with reason)"). */
export function errorText(e: IngestError): string {
  switch (e.kind) {
    case "model_unavailable":
      return `Model unavailable: ${e.detail}`;
    case "model_timeout":
      return `Model timed out during ${e.step.replace("_", " ")}`;
    case "not_utf8":
      return "Not UTF-8 text";
  }
}

const fileName = (path: string) => path.split("/").pop() ?? path;

/** Re-renders every `ms` while `on`, for elapsed-time counters. */
function useNow(on: boolean, ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [on, ms]);
  return now;
}

/** Smoothed "about N min left" from the latest status; null when unknown. */
function useEta(status: JobsStatusResponse | null): string | null {
  const ref = useRef<EtaState | null>(null);
  const lastStatus = useRef<JobsStatusResponse | null>(null);
  if (status !== lastStatus.current) {
    lastStatus.current = status;
    const now = Date.now();
    ref.current = smoothEta(ref.current, rawEtaSeconds(status, now), now);
  }
  return formatEta(ref.current?.value);
}

/**
 * Screen-reader announcements at milestones only (start, first failures, finish), never on every
 * poll, so the tray does not chatter while 50 files tick by.
 */
function useMilestones(inFlight: number, done: number, failed: number, total: number): string {
  const [message, setMessage] = useState("");
  const prev = useRef({ inFlight: 0, failed });
  useEffect(() => {
    const p = prev.current;
    if (p.inFlight === 0 && inFlight > 0) setMessage(`Indexing ${total} ${plural(total, "file")}`);
    else if (p.inFlight > 0 && inFlight === 0)
      setMessage(failed > 0 ? `Indexing finished: ${done} linked, ${failed} failed` : `Indexing finished: ${done} ${plural(done, "file")} linked`);
    else if (inFlight > 0 && failed > p.failed) setMessage(`${failed} ${plural(failed, "file")} failed so far`);
    prev.current = { inFlight, failed };
  }, [inFlight, done, failed, total]);
  return message;
}

function IndexingRow({ f, now }: { f: FileProgress; now: number }) {
  const i = stageIndex(f.stage);
  const elapsed = formatElapsed(f.started_at, now);
  return (
    <li className="tray-file is-indexing">
      <span className="status-dot status-indexing" aria-hidden="true" />
      <div className="tray-file-main">
        <div className="tray-file-line">
          <span className="tray-file-name" title={f.path}>
            {fileName(f.path)}
          </span>
          {elapsed && (
            <span className="tray-elapsed" aria-label={`running for ${elapsed}`}>
              {elapsed}
            </span>
          )}
        </div>
        <StageStepper stage={f.stage} />
        <span className="tray-stage">{i >= 0 ? STAGES[i]!.long : "Starting…"}</span>
      </div>
    </li>
  );
}

function FileRow({ f, onOpenDocument }: { f: FileProgress; onOpenDocument: Props["onOpenDocument"] }) {
  const docId = f.outcome?.kind === "indexed" ? f.outcome.document_id : null;
  const links = f.outcome?.kind === "indexed" ? f.outcome.link_count : null;
  const unchanged = f.outcome?.kind === "skipped";
  return (
    <li className={`tray-file is-${f.status}`}>
      <span className={`status-dot status-${f.status}`} aria-hidden="true" />
      <span className="tray-file-name" title={f.path}>
        {docId ? (
          <button type="button" className="link-btn" onClick={() => onOpenDocument(docId, fileName(f.path))}>
            {fileName(f.path)}
          </button>
        ) : (
          fileName(f.path)
        )}
        {f.error && <span className="error small tray-reason">{errorText(f.error)}</span>}
      </span>
      {links !== null && (
        <span className="tray-meta">
          {links} {plural(links, "link")}
        </span>
      )}
      {unchanged && <span className="tray-meta">unchanged</span>}
      <span className={`status-pill status-${f.status}`}>{STATUS_LABEL[f.status]}</span>
    </li>
  );
}

/** UP-4 progress tray: per-file status from GET /api/jobs/status, ignored files, and the done card. */
export function ProgressTray({ status, ignored, summary, onDismiss, onOpenDocument, onZoomCluster }: Props) {
  const [open, setOpen] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const files = status?.files ?? [];
  const counts = status?.counts ?? {};
  const inFlight = (counts.pending ?? 0) + (counts.running ?? 0);
  const done = counts.done ?? 0;
  const failed = counts.failed ?? 0;
  const total = inFlight + done + failed;
  const anyIndexing = files.some((f) => f.status === "indexing");
  const now = useNow(anyIndexing && open);
  const eta = useEta(status);
  const milestone = useMilestones(inFlight, done, failed, total);

  // Open by itself when a new batch starts, even if the user collapsed it last time.
  const wasInFlight = useRef(inFlight > 0);
  useEffect(() => {
    if (inFlight > 0 && !wasInFlight.current) setOpen(true);
    wasInFlight.current = inFlight > 0;
  }, [inFlight]);

  if (!files.length && !ignored.length && !summary) return null;

  const pct = total ? Math.round(((done + failed) / total) * 100) : 100;
  const heading = inFlight > 0 ? `Indexing ${done + failed} of ${total} files` : failed > 0 ? `Done, ${failed} failed` : "All files indexed";
  const { visible, hidden } = groupTrayFiles(files);
  const rows = showAll ? [...visible, ...hidden] : visible;
  const hiddenQueued = hidden.filter((f) => f.status === "queued").length;
  const hiddenDone = hidden.length - hiddenQueued;

  return (
    <section className="tray" aria-label="Upload progress">
      <header className="tray-head">
        <button type="button" className="tray-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <span className="tray-title">
            {heading}
            {inFlight > 0 && eta && <span className="tray-eta"> · {eta} left</span>}
          </span>
          <span aria-hidden="true" className="muted tray-chevron">
            {open ? "▾" : "▴"}
          </span>
        </button>
        {inFlight === 0 && (
          <button type="button" className="icon-btn small" onClick={onDismiss} aria-label="Dismiss progress">
            ×
          </button>
        )}
      </header>
      <div className="progress" role="progressbar" aria-label="Indexing progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <p className="sr-only" role="status">
        {milestone}
      </p>
      {open && (
        <div className="tray-body">
          {summary && inFlight === 0 && (
            <div className="tray-summary">
              <p className="tray-summary-line">
                <strong>{summary.stats.documents}</strong> {plural(summary.stats.documents, "document")},{" "}
                <strong>{summary.stats.clusters}</strong> {plural(summary.stats.clusters, "theme")},{" "}
                <strong>{summary.stats.links}</strong> {plural(summary.stats.links, "connection")}
              </p>
              {summary.topClusters.length > 0 && (
                <div className="tray-themes">
                  <span className="muted small">Explore:</span>
                  {summary.topClusters.map((c) => (
                    <button key={c.id} type="button" className="chip-btn" onClick={() => onZoomCluster(c.id)}>
                      <span className="swatch" style={{ background: c.color }} aria-hidden="true" />
                      {c.label ?? "Unlabelled theme"}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {rows.length > 0 && (
            <ul className="tray-files" aria-label="Files">
              {rows.map((f) =>
                f.status === "indexing" ? <IndexingRow key={f.job_id} f={f} now={now} /> : <FileRow key={f.job_id} f={f} onOpenDocument={onOpenDocument} />,
              )}
            </ul>
          )}
          {hidden.length > 0 && (
            <button type="button" className="link-btn small tray-more" aria-expanded={showAll} onClick={() => setShowAll((s) => !s)}>
              {showAll
                ? "Show fewer"
                : `Show ${hidden.length} more (${[hiddenQueued && `${hiddenQueued} queued`, hiddenDone && `${hiddenDone} done`].filter(Boolean).join(", ")})`}
            </button>
          )}
          {ignored.length > 0 && (
            <details className="tray-ignored">
              <summary>
                {ignored.length} ignored {ignored.length === 1 ? "file" : "files"}
              </summary>
              <ul>
                {ignored.map((f) => (
                  <li key={f.path}>
                    <span className="mono small">{f.path}</span> <span className="muted small">({IGNORED_REASON[f.reason]})</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
