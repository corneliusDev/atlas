import { useEffect, useRef, useState } from "react";
import { plural } from "../lib/progress";

export interface FileDrag {
  active: boolean;
  /** Files being dragged, when the browser exposes it (it hides names until the drop). */
  count: number | null;
}

const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");

function fileCount(e: DragEvent): number | null {
  const items = e.dataTransfer?.items;
  if (!items || items.length === 0) return null;
  const n = [...items].filter((i) => i.kind === "file").length;
  return n > 0 ? n : null;
}

/**
 * Tracks files dragged anywhere over the window. Uses an enter/leave depth counter so moving
 * between child elements does not flicker, and hands drops nobody else handled to `onDrop`
 * (the first-run drop zone handles its own drops and stops propagation).
 */
export function useWindowFileDrag(onDrop: (files: File[]) => void): FileDrag {
  const [drag, setDrag] = useState<FileDrag>({ active: false, count: null });
  const depth = useRef(0);
  const onDropRef = useRef(onDrop);
  onDropRef.current = onDrop;

  useEffect(() => {
    const reset = () => {
      depth.current = 0;
      setDrag((d) => (d.active ? { active: false, count: null } : d));
    };
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current += 1;
      const count = fileCount(e);
      setDrag((d) => (d.active && d.count === count ? d : { active: true, count: count ?? d.count }));
    };
    const over = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const leave = () => {
      if (depth.current === 0) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) reset();
    };
    const dropCapture = (e: DragEvent) => {
      if (hasFiles(e)) reset();
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e) || e.defaultPrevented) return;
      e.preventDefault();
      const files = [...(e.dataTransfer?.files ?? [])];
      if (files.length) onDropRef.current(files);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", dropCapture, true);
    window.addEventListener("drop", drop);
    window.addEventListener("dragend", reset);
    window.addEventListener("blur", reset);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", dropCapture, true);
      window.removeEventListener("drop", drop);
      window.removeEventListener("dragend", reset);
      window.removeEventListener("blur", reset);
    };
  }, []);

  return drag;
}

export function dropOverlayText(count: number | null): string {
  return count ? `Drop to upload ${count} Markdown ${plural(count, "file")}` : "Drop to upload Markdown files";
}

/** Full-window overlay shown while files are dragged over the app. */
export function DropOverlay({ drag, busy }: { drag: FileDrag; busy: boolean }) {
  if (!drag.active) return null;
  return (
    <div className="drop-overlay" data-testid="drop-overlay">
      <div className="drop-overlay-card">
        <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true" className="drop-overlay-icon">
          <path d="M12 15V4M7.5 8.5 12 4l4.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" strokeLinecap="round" />
        </svg>
        <strong>{busy ? "Wait for the current upload to finish" : dropOverlayText(drag.count)}</strong>
        <span className="muted small">{busy ? "One upload at a time" : ".md, .markdown or a zipped folder, up to 5 MB each"}</span>
      </div>
    </div>
  );
}
