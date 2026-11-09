import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ClusterInfo, LinkVerdict } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { docKey } from "../lib/graphModel";
import { FeedbackButtons } from "./FeedbackButtons";
import { MarkdownView } from "./MarkdownView";

interface Props {
  id: string;
  clusters: ReadonlyMap<string, ClusterInfo>;
  onOpen: (key: string, label: string) => void;
  onWhy: (a: string, b: string) => void;
  onFeedback: (a: string, b: string, verdict: LinkVerdict) => Promise<void>;
  onLoaded?: (key: string, title: string) => void;
  /** Bumped by the parent after feedback elsewhere so the related list refreshes. */
  version: number;
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.map(formatValue).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** DV-1 / DV-2: rendered document with summary, tags, frontmatter, related docs, topics, backlinks. */
export function DocumentPanel({ id, clusters, onOpen, onWhy, onFeedback, onLoaded, version }: Props) {
  const { data: doc, error, loading } = useAsync((signal) => api.document(id, undefined, signal), [id, version]);
  const [overrides, setOverrides] = useState<Record<string, LinkVerdict>>({});
  const [announce, setAnnounce] = useState("");
  const [showSource, setShowSource] = useState(true);

  useEffect(() => setOverrides({}), [id, version]);
  useEffect(() => {
    if (doc) onLoaded?.(docKey(doc.id), doc.title);
  }, [doc, onLoaded]);

  if (error) return <p role="alert" className="panel-pad">Could not load this document: {error.message}</p>;
  if (!doc) return <p className="panel-pad" aria-busy={loading}>Loading document…</p>;

  const cluster = doc.cluster_id ? clusters.get(doc.cluster_id) : undefined;
  const related = doc.related
    .map((r) => ({ ...r, feedback: overrides[r.document.id] ?? r.feedback }))
    .filter((r) => r.feedback !== "hidden");
  const fm = Object.entries(doc.frontmatter);
  const ghosts = doc.outgoing.filter((o) => !o.resolved);

  return (
    <article className="doc" aria-labelledby="doc-title">
      <header className="doc-head">
        <p className="muted small mono doc-path">{doc.path}</p>
        <h2 id="doc-title" className="doc-title">
          {doc.title}
        </h2>
        <div className="doc-meta">
          {cluster && (
            <span className="cluster-chip">
              <span className="swatch" style={{ background: cluster.color }} aria-hidden="true" />
              {cluster.label ?? "Unlabelled theme"}
            </span>
          )}
          {doc.origin === "upload" && <span className="badge">Uploaded</span>}
          <span className="muted small">Indexed {new Date(doc.indexed_at).toLocaleDateString()}</span>
        </div>
        {doc.tags.length > 0 && (
          <ul className="tag-row" aria-label="Tags">
            {doc.tags.map((t) => (
              <li key={t} className="tag static">
                #{t}
              </li>
            ))}
          </ul>
        )}
      </header>

      <section className="doc-section" aria-labelledby="doc-summary">
        <h3 id="doc-summary" className="section-title">
          Summary
        </h3>
        <p className="summary">{doc.summary ?? <span className="muted">Summary pending.</span>}</p>
      </section>

      <section className="doc-section" aria-labelledby="doc-related">
        <h3 id="doc-related" className="section-title">
          Related documents <span className="count">{related.length}</span>
        </h3>
        <p className="sr-only" aria-live="polite">
          {announce}
        </p>
        {related.length === 0 ? (
          <p className="muted small">No related documents above the threshold yet.</p>
        ) : (
          <ul className="related-list">
            {related.map((r) => (
              <li key={r.document.id} className="related">
                <div className="related-top">
                  <button type="button" className="link-btn strong" onClick={() => onOpen(docKey(r.document.id), r.document.title)}>
                    {r.document.title}
                  </button>
                  {r.score !== null ? (
                    <span className="score-pill" title="Similarity">
                      <span className="meter" aria-hidden="true">
                        <span style={{ width: `${Math.round(r.score * 100)}%` }} />
                      </span>
                      {Math.round(r.score * 100)}%
                    </span>
                  ) : (
                    <span className="badge">Added by you</span>
                  )}
                </div>
                <p className="reason">{r.reason ?? <span className="muted">Reason pending.</span>}</p>
                <div className="related-actions">
                  <button type="button" className="chip-btn" onClick={() => onWhy(doc.id, r.document.id)}>
                    Why connected?
                  </button>
                  <FeedbackButtons
                    value={r.feedback}
                    label={`${doc.title} and ${r.document.title}`}
                    onVerdict={async (v) => {
                      await onFeedback(doc.id, r.document.id, v);
                      setOverrides((o) => ({ ...o, [r.document.id]: v }));
                      setAnnounce(v === "hidden" ? `Hid the link to ${r.document.title}.` : `Confirmed the link to ${r.document.title}.`);
                    }}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {doc.topics.length > 0 && (
        <section className="doc-section" aria-labelledby="doc-topics">
          <h3 id="doc-topics" className="section-title">
            Topics
          </h3>
          <ul className="topic-row">
            {doc.topics.map((t) => (
              <li key={t.id}>
                <button type="button" className="topic-chip" onClick={() => onOpen(`topic:${t.id}`, t.name)}>
                  {t.name}
                  <span className="muted small"> · {t.kind}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="doc-section" aria-labelledby="doc-backlinks">
        <h3 id="doc-backlinks" className="section-title">
          Backlinks <span className="count">{doc.backlinks.length}</span>
        </h3>
        {doc.backlinks.length === 0 ? (
          <p className="muted small">No notes link here with [[wikilinks]].</p>
        ) : (
          <ul className="plain-list compact">
            {doc.backlinks.map((b, i) => (
              <li key={`${b.document.id}-${i}`}>
                <button type="button" className="link-btn" onClick={() => onOpen(docKey(b.document.id), b.document.title)}>
                  {b.document.title}
                </button>
                {b.anchor && <span className="muted small"> › {b.anchor}</span>}
              </li>
            ))}
          </ul>
        )}
        {ghosts.length > 0 && (
          <p className="muted small">
            Links to unwritten notes:{" "}
            {ghosts.map((g, i) => (
              <span key={g.target_name}>
                {i > 0 && ", "}
                <button type="button" className="link-btn subtle ghost-link" onClick={() => onOpen(`ghost:${g.target_name}`, g.target_name)}>
                  {g.target_name}
                </button>
              </span>
            ))}
          </p>
        )}
      </section>

      {fm.length > 0 && (
        <section className="doc-section" aria-labelledby="doc-fm">
          <h3 id="doc-fm" className="section-title">
            Frontmatter
          </h3>
          <dl className="frontmatter">
            {fm.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{formatValue(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <section className="doc-section" aria-labelledby="doc-body">
        <div className="section-row">
          <h3 id="doc-body" className="section-title">
            Note
          </h3>
          <button type="button" className="link-btn small" aria-expanded={showSource} onClick={() => setShowSource((s) => !s)}>
            {showSource ? "Collapse" : "Expand"}
          </button>
        </div>
        {showSource && <MarkdownView markdown={doc.markdown} outgoing={doc.outgoing} onOpen={onOpen} />}
      </section>
    </article>
  );
}
