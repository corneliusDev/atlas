import { useEffect } from "react";
import { IGNORED_REASON, formatBytes, plural, uploadSummary } from "../lib/progress";
import type { UploadController } from "./UploadZone";

/** Success without problems hides itself; anything the user should read stays until dismissed. */
export const UPLOAD_CARD_AUTO_HIDE_MS = 6000;
export const UPLOAD_CARD_AUTO_HIDE_IGNORED_MS = 12_000;

/** Upload status card above the progress tray: bytes, then server processing, then the result. */
export function UploadCard({ upload }: { upload: UploadController }) {
  const { state, retry, dismiss } = upload;

  useEffect(() => {
    if (state.phase !== "success") return;
    const ms = state.result.ignored.length ? UPLOAD_CARD_AUTO_HIDE_IGNORED_MS : UPLOAD_CARD_AUTO_HIDE_MS;
    const id = window.setTimeout(dismiss, ms);
    return () => window.clearTimeout(id);
  }, [state, dismiss]);

  if (state.phase === "idle") return null;

  const what = `${state.files} ${plural(state.files, "file")} · ${formatBytes(state.bytes)}`;
  let body;
  let announcement = "";

  if (state.phase === "sending") {
    const pct = state.total > 0 ? Math.min(99, Math.floor((state.loaded / state.total) * 100)) : 0;
    announcement = `Uploading ${state.files} ${plural(state.files, "file")}`;
    body = (
      <>
        <div className="upload-card-line">
          <span className="upload-card-title">Uploading {what}</span>
          <span className="upload-card-pct">{pct}%</span>
        </div>
        <div className="progress progress-card" role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <span style={{ width: `${pct}%` }} />
        </div>
      </>
    );
  } else if (state.phase === "processing") {
    announcement = "Processing on server";
    body = (
      <>
        <div className="upload-card-line">
          <span className="upload-card-title">Uploading {what}</span>
          <span className="upload-card-pct">100%</span>
        </div>
        <div className="progress progress-card is-indeterminate" role="progressbar" aria-label="Upload progress" aria-valuetext="Processing on server">
          <span />
        </div>
        <p className="upload-card-note muted">Processing on server…</p>
      </>
    );
  } else if (state.phase === "success") {
    const { headline, ignored } = uploadSummary(state.result);
    announcement = ignored ? `${headline}, ${ignored}` : headline;
    body = (
      <>
        <div className="upload-card-line">
          <span className="upload-card-check" aria-hidden="true" />
          <span className="upload-card-title grow">
            {headline}
            {ignored && <span className="muted"> · {ignored}</span>}
          </span>
          <button type="button" className="icon-btn small" onClick={dismiss} aria-label="Dismiss upload status">
            ×
          </button>
        </div>
        {state.result.ignored.length > 0 && (
          <ul className="upload-card-ignored">
            {state.result.ignored.slice(0, 4).map((f) => (
              <li key={f.path}>
                <span className="mono">{f.path}</span> <span className="muted">{IGNORED_REASON[f.reason]}</span>
              </li>
            ))}
            {state.result.ignored.length > 4 && <li className="muted">and {state.result.ignored.length - 4} more</li>}
          </ul>
        )}
      </>
    );
  } else {
    body = (
      <div role="alert">
        <div className="upload-card-line">
          <span className="upload-card-title grow error">Upload failed</span>
          <button type="button" className="icon-btn small" onClick={dismiss} aria-label="Dismiss upload status">
            ×
          </button>
        </div>
        <p className="upload-card-note muted">
          {what}. {state.message}
        </p>
        <div className="upload-card-actions">
          <button type="button" className="btn btn-small" onClick={() => void retry()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <section className={`upload-card is-${state.phase}`} aria-label="Upload status">
      {body}
      <p className="sr-only" role="status">
        {announcement}
      </p>
    </section>
  );
}
