import { useEffect } from "react";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";

interface Props {
  nodeKey: string;
  label: string;
  onOpen: (key: string, label: string) => void;
  onLoaded?: (key: string, title: string) => void;
}

/** Side panel for topic and ghost nodes: what kind of node it is and which documents touch it. */
export function NodePanel({ nodeKey, label, onOpen, onLoaded }: Props) {
  const { data, error, loading } = useAsync((signal) => api.localGraph(nodeKey, 1, undefined, signal), [nodeKey]);
  const isGhost = nodeKey.startsWith("ghost:");
  const self = data?.nodes.find((n) => n.key === nodeKey);
  const title = self?.label ?? label;

  useEffect(() => {
    if (self) onLoaded?.(self.key, self.label);
  }, [self, onLoaded]);

  const weight = new Map<string, number>();
  for (const e of data?.edges ?? []) {
    if (e.source === nodeKey) weight.set(e.target, e.weight);
    if (e.target === nodeKey) weight.set(e.source, e.weight);
  }
  const docs = (data?.nodes ?? [])
    .filter((n) => n.key !== nodeKey && n.ref.kind === "document" && weight.has(n.key))
    .sort((a, b) => (weight.get(b.key) ?? 0) - (weight.get(a.key) ?? 0) || a.label.localeCompare(b.label));

  return (
    <article className="doc" aria-labelledby="node-title">
      <header className="doc-head">
        <p className="muted small">{isGhost ? "Unwritten note" : `Topic${self?.topic_kind ? ` · ${self.topic_kind}` : ""}`}</p>
        <h2 id="node-title" className="doc-title">
          {isGhost ? title : self?.topic_kind === "tag" ? `#${title}` : title}
        </h2>
      </header>
      <section className="doc-section">
        {isGhost && (
          <p className="summary">
            No note called “{title}” exists yet. It shows up because other notes link to it with [[wikilinks]].
          </p>
        )}
        <h3 className="section-title">
          {isGhost ? "Linked from" : "Documents"} <span className="count">{docs.length}</span>
        </h3>
        {error && <p role="alert">Could not load connections: {error.message}</p>}
        {loading && !data && <p aria-busy="true">Loading…</p>}
        <ul className="plain-list compact">
          {docs.map((n) => (
            <li key={n.key}>
              <button type="button" className="link-btn" onClick={() => onOpen(n.key, n.label)}>
                {n.label}
              </button>
              {!isGhost && <span className="muted small"> · salience {Math.round((weight.get(n.key) ?? 0) * 100)}%</span>}
              {n.summary && <p className="muted small clamp-2">{n.summary}</p>}
            </li>
          ))}
        </ul>
      </section>
    </article>
  );
}
