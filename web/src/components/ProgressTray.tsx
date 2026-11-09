import { useState } from "react";
import type { ClusterInfo, FileProgress, FileStatus, GraphStats, IgnoredFile, IngestError, JobsStatusResponse } from "../api/types";

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

const IGNORED_REASON: Record<IgnoredFile["reason"], string> = {
  not_markdown: "not a Markdown file",
  too_large: "larger than 5 MB",
  invalid_path: "invalid path",
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

const plural = (n: number, word: string) => (n === 1 ? word : `${word}s`);

const fileName = (path: string) => path.split("/").pop() ?? path;

function FileRow({ f, onOpenDocument }: { f: FileProgress; onOpenDocument: Props["onOpenDocument"] }) {
  const docId = f.outcome?.kind === "indexed" ? f.outcome.document_id : null;
  return (
    <li className="tray-file">
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
      <span className={`status-pill status-${f.status}`}>{STATUS_LABEL[f.status]}</span>
    </li>
  );
}

/** UP-4 progress tray: per-file status from GET /api/jobs/status, ignored files, and the done card. */
export function ProgressTray({ status, ignored, summary, onDismiss, onOpenDocument, onZoomCluster }: Props) {
  const [open, setOpen] = useState(true);
  const files = status?.files ?? [];
  if (!files.length && !ignored.length && !summary) return null;

  const counts = status?.counts ?? {};
  const inFlight = (counts.pending ?? 0) + (counts.running ?? 0);
  const done = counts.done ?? 0;
  const failed = counts.failed ?? 0;
  const total = inFlight + done + failed;
  const pct = total ? Math.round(((done + failed) / total) * 100) : 100;
  const heading = inFlight > 0 ? `Indexing ${done + failed} of ${total} files` : failed > 0 ? `Done, ${failed} failed` : "All files indexed";

  return (
    <section className="tray" aria-label="Upload progress">
      <header className="tray-head">
        <button type="button" className="tray-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <span className="tray-title" aria-live="polite">
            {heading}
          </span>
          <span aria-hidden="true" className="muted">
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
          {files.length > 0 && (
            <ul className="tray-files" aria-label="Files">
              {files.slice(0, 200).map((f) => (
                <FileRow key={f.job_id} f={f} onOpenDocument={onOpenDocument} />
              ))}
            </ul>
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
