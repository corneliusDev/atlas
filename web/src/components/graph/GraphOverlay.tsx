import { plural } from "../../lib/progress";

export type GraphOverlayState =
  | { kind: "loading" }
  | { kind: "arranging"; notes: number; links: number; progress: number; leaving?: boolean }
  | { kind: "error"; message: string; onRetry: () => void };

export function arrangingText(notes: number, links: number): string {
  return `Arranging ${notes} ${plural(notes, "note")} and ${links} ${plural(links, "link")}…`;
}

/**
 * Status layer over the graph area: loading data, laying it out, or a failed request.
 * Only the error state takes pointer events; the others let the graph stay interactive.
 */
export function GraphOverlay({ state }: { state: GraphOverlayState }) {
  if (state.kind === "loading") {
    return (
      <div className="graph-overlay is-loading" role="status" data-testid="graph-overlay">
        <div className="graph-overlay-card">
          <span className="spinner" aria-hidden="true" />
          <span>Loading your notes…</span>
        </div>
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="graph-overlay is-error" data-testid="graph-overlay">
        <div className="graph-overlay-card" role="alert">
          <strong>Could not load the graph</strong>
          <span className="muted small">{state.message}</span>
          <button type="button" className="btn btn-small" onClick={state.onRetry}>
            Retry
          </button>
        </div>
      </div>
    );
  }
  const pct = Math.round(Math.min(1, Math.max(0, state.progress)) * 100);
  return (
    <div className={`graph-overlay is-arranging ${state.leaving ? "is-leaving" : ""}`} data-testid="graph-overlay">
      <div className="graph-overlay-card">
        <span role="status">{arrangingText(state.notes, state.links)}</span>
        <div className="progress progress-card" role="progressbar" aria-label="Layout progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <span style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}
