import { Fragment, useEffect, useId, useRef, useState } from "react";
import { api } from "../api/client";
import type { ClusterInfo, SearchHit } from "../api/types";
import { Modal } from "./Modal";

interface Props {
  initialQuery?: string;
  clusters: ReadonlyMap<string, ClusterInfo>;
  onClose: () => void;
  /** Called with every result set so matching nodes glow in the graph (SR-2). */
  onResults: (query: string, hits: SearchHit[]) => void;
  onPick: (hit: SearchHit) => void;
  debounceMs?: number;
}

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'", "&#39;": "'" };
const unescapeHtml = (s: string) => s.replace(/&(?:amp|lt|gt|quot|#x27|#39);/g, (e) => ENTITIES[e] ?? e);

/** Server snippets are HTML-escaped text with matches in <mark> (OpenAPI SearchHit.snippet).
 * They are parsed into React nodes, never injected as HTML. Plain snippets fall back to
 * highlighting the query terms client-side. */
function Highlighted({ text, query }: { text: string; query: string }) {
  if (text.includes("<mark>")) {
    const parts = text.split(/<\/?mark>/);
    return (
      <>
        {parts.map((p, i) =>
          i % 2 === 1 ? <mark key={i}>{unescapeHtml(p)}</mark> : <Fragment key={i}>{unescapeHtml(p)}</Fragment>,
        )}
      </>
    );
  }
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 1)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return <>{unescapeHtml(text)}</>;
  const parts = unescapeHtml(text).split(new RegExp(`(${terms.join("|")})`, "gi"));
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1 ? <mark key={i}>{p}</mark> : <Fragment key={i}>{p}</Fragment>))}
    </>
  );
}

/** Cmd+K hybrid search (SR-1): results with snippets; Enter jumps to the best match. */
export function SearchPalette({ initialQuery = "", clusters, onClose, onResults, onPick, debounceMs = 180 }: Props) {
  const [query, setQuery] = useState(initialQuery);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [active, setActive] = useState(0);
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [tookMs, setTookMs] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const onResultsRef = useRef(onResults);
  onResultsRef.current = onResults;

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits([]);
      setState("idle");
      onResultsRef.current("", []);
      return;
    }
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      setState("loading");
      api.search(q, { limit: 20 }, ctrl.signal).then(
        (res) => {
          setHits(res.hits);
          setActive(0);
          setTookMs(res.took_ms);
          setState("done");
          onResultsRef.current(q, res.hits);
        },
        () => {
          if (!ctrl.signal.aborted) setState("error");
        },
      );
    }, debounceMs);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [query, debounceMs]);

  const pick = (hit: SearchHit | undefined) => {
    if (!hit) return;
    onPick(hit);
    onClose();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(hits.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(hits[active] ?? hits[0]);
    }
  };

  const optionId = (i: number) => `${listId}-opt-${i}`;
  return (
    <Modal title="Search notes" onClose={onClose} className="palette" initialFocus={inputRef} hideTitle>
      <div className="palette-input">
        <span aria-hidden="true" className="palette-icon">
          ⌕
        </span>
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-label="Search notes"
          aria-expanded={hits.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={hits.length ? optionId(active) : undefined}
          placeholder="Search by keyword or meaning…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <kbd>esc</kbd>
      </div>
      <ul id={listId} role="listbox" aria-label="Search results" className="palette-results">
        {hits.map((h, i) => {
          const cluster = h.cluster_id ? clusters.get(h.cluster_id) : undefined;
          return (
            <li
              key={`${h.document_id}-${h.chunk_id ?? i}`}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className={i === active ? "is-active" : undefined}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(h)}
            >
              <div className="hit-top">
                {cluster && <span className="swatch" style={{ background: cluster.color }} aria-hidden="true" />}
                <span className="hit-title">
                  <Highlighted text={h.title} query={query} />
                </span>
                {h.heading_path.length > 1 && <span className="muted small">› {h.heading_path.slice(1).join(" › ")}</span>}
                <span className="hit-kind muted small">
                  {h.keyword_rank !== null && h.semantic_rank !== null ? "keyword + meaning" : h.keyword_rank !== null ? "keyword" : "meaning"}
                </span>
              </div>
              <p className="hit-snippet">
                <Highlighted text={h.snippet} query={query} />
              </p>
              <p className="muted small mono">{h.path}</p>
            </li>
          );
        })}
      </ul>
      <div className="palette-foot muted small" aria-live="polite">
        {state === "loading" && "Searching…"}
        {state === "error" && "Search failed. Is the API running?"}
        {state === "done" && (hits.length ? `${hits.length} results${tookMs !== null ? ` in ${tookMs} ms` : ""} · ↑↓ to move, Enter to open` : "No matches")}
        {state === "idle" && "Matches glow in the graph as you type."}
      </div>
    </Modal>
  );
}
