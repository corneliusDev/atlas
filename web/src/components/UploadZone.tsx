import { useCallback, useId, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { UploadResponse } from "../api/types";

export const ACCEPT = ".md,.markdown,.zip";

interface Props {
  onUploaded: (res: UploadResponse) => void;
  /** "hero" is the first-run empty state; "button" is the compact header control. */
  variant: "hero" | "button";
  children?: ReactNode;
}

/** Collects files dropped on (or picked into) the zone and POSTs them to /api/uploads (UP-2). */
export function useUpload(onUploaded: (res: UploadResponse) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = useCallback(
    async (files: readonly File[]) => {
      if (!files.length) return;
      setBusy(true);
      setError(null);
      try {
        onUploaded(await api.upload(files));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setBusy(false);
      }
    },
    [onUploaded],
  );
  return { busy, error, send };
}

export function UploadZone({ onUploaded, variant, children }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const [over, setOver] = useState(false);
  const { busy, error, send } = useUpload(onUploaded);

  const pick = () => inputRef.current?.click();
  const input = (
    <input
      ref={inputRef}
      id={inputId}
      type="file"
      multiple
      accept={ACCEPT}
      className="sr-only"
      tabIndex={-1}
      aria-label="Choose Markdown files to upload"
      data-testid="upload-input"
      onChange={(e) => {
        const files = [...(e.target.files ?? [])];
        e.target.value = "";
        void send(files);
      }}
    />
  );

  if (variant === "button") {
    return (
      <>
        <button type="button" className="btn btn-ghost" onClick={pick} disabled={busy}>
          {busy ? "Uploading…" : "Upload"}
        </button>
        {input}
        {error && (
          <span role="alert" className="error small">
            {error}
          </span>
        )}
      </>
    );
  }

  return (
    <div
      className={`dropzone ${over ? "is-over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setOver(false);
        void send([...e.dataTransfer.files]);
      }}
    >
      <div className="dropzone-art" aria-hidden="true">
        <svg viewBox="0 0 64 64" width="56" height="56" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="16" cy="20" r="5" />
          <circle cx="46" cy="16" r="4" />
          <circle cx="36" cy="44" r="6" />
          <circle cx="12" cy="46" r="3" strokeDasharray="2 2" />
          <path d="M20 22l11 18M42 19l-5 19M21 19l21-3M15 43l15 1" opacity="0.55" />
        </svg>
      </div>
      <h2 className="dropzone-title">Drop your .md files here</h2>
      <p className="muted">Markdown files or a zipped folder, up to 5 MB each. Atlas reads them, finds the links between them and draws the map.</p>
      {children}
      <button type="button" className="btn btn-primary" onClick={pick} disabled={busy}>
        {busy ? "Uploading…" : "Choose files"}
      </button>
      {input}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}
