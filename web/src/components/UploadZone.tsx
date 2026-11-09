import { useCallback, useId, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { UploadResponse } from "../api/types";

export const ACCEPT = ".md,.markdown,.zip";

/** Where one upload is: bytes going out, server reading them, then the result. */
export type UploadState =
  | { phase: "idle" }
  | { phase: "sending"; files: number; bytes: number; loaded: number; total: number }
  | { phase: "processing"; files: number; bytes: number }
  | { phase: "success"; files: number; bytes: number; result: UploadResponse }
  | { phase: "error"; files: number; bytes: number; message: string };

export interface UploadController {
  state: UploadState;
  /** True while bytes are in flight or the server is processing; further sends are ignored. */
  busy: boolean;
  send: (files: readonly File[]) => Promise<void>;
  /** Re-sends the files of the last failed upload. */
  retry: () => Promise<void>;
  dismiss: () => void;
}

/**
 * One upload at a time (UP-2): POSTs to /api/uploads with byte progress and exposes the state the
 * upload card shows. A second drop or pick while busy is ignored, so nothing is sent twice.
 */
export function useUpload(onUploaded: (res: UploadResponse) => void): UploadController {
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const inFlight = useRef(false);
  const lastFiles = useRef<readonly File[]>([]);
  const onUploadedRef = useRef(onUploaded);
  onUploadedRef.current = onUploaded;

  const send = useCallback(async (files: readonly File[]) => {
    if (!files.length || inFlight.current) return;
    inFlight.current = true;
    lastFiles.current = files;
    const count = files.length;
    const bytes = files.reduce((s, f) => s + f.size, 0);
    setState({ phase: "sending", files: count, bytes, loaded: 0, total: bytes });
    try {
      const result = await api.upload(files, {
        onProgress: (loaded, total) =>
          setState((s) => {
            if (s.phase !== "sending" && s.phase !== "processing") return s;
            if (total > 0 && loaded >= total) return { phase: "processing", files: count, bytes };
            return { phase: "sending", files: count, bytes, loaded, total };
          }),
      });
      setState({ phase: "success", files: count, bytes, result });
      onUploadedRef.current(result);
    } catch (e) {
      setState({ phase: "error", files: count, bytes, message: e instanceof Error ? e.message : "Upload failed" });
    } finally {
      inFlight.current = false;
    }
  }, []);

  const retry = useCallback(() => send(lastFiles.current), [send]);
  const dismiss = useCallback(() => setState((s) => (s.phase === "sending" || s.phase === "processing" ? s : { phase: "idle" })), []);
  const busy = state.phase === "sending" || state.phase === "processing";
  return { state, busy, send, retry, dismiss };
}

interface Props {
  /** "hero" is the first-run empty state; "button" is the compact header control. */
  variant: "hero" | "button";
  /** Shared upload controller (the app has one, so every entry point feeds the same card). */
  upload?: UploadController;
  /** Used when no controller is passed (standalone use). */
  onUploaded?: (res: UploadResponse) => void;
  children?: ReactNode;
}

const noop = () => {};

/** File picker / drop target that hands files to the upload controller (UP-2). */
export function UploadZone({ variant, upload, onUploaded, children }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const [over, setOver] = useState(false);
  const own = useUpload(onUploaded ?? noop);
  const { busy, send } = upload ?? own;

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
    </div>
  );
}
