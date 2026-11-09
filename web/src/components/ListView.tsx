import { useId, useMemo, useState } from "react";
import type { GraphNode, GraphView } from "../api/types";

interface Props {
  view: GraphView;
  selectedKey: string | null;
  highlightKeys: ReadonlySet<string>;
  onSelect: (key: string, label: string) => void;
}

type Sort = "connections" | "name" | "type";

const KIND_LABEL: Record<GraphNode["ref"]["kind"], string> = {
  document: "Document",
  topic: "Topic",
  ghost: "Unwritten note",
};

/**
 * Accessible equivalent of the current graph view (NFR: WCAG 2.1 AA, "a list view of every
 * graph view"): one table row per node with its cluster and connections, all keyboard reachable.
 */
export function ListView({ view, selectedKey, highlightKeys, onSelect }: Props) {
  const [sort, setSort] = useState<Sort>("connections");
  const [query, setQuery] = useState("");
  const filterId = useId();

  const clusterLabel = useMemo(() => new Map(view.clusters.map((c) => [c.id, c])), [view.clusters]);
  const neighbors = useMemo(() => {
    const byKey = new Map(view.nodes.map((n) => [n.key, n]));
    // A pair can be joined by several edges (a wiki link and a semantic link), so dedupe by key.
    const map = new Map<string, Map<string, GraphNode>>();
    const add = (from: GraphNode, to: GraphNode) => {
      const m = map.get(from.key) ?? new Map<string, GraphNode>();
      m.set(to.key, to);
      map.set(from.key, m);
    };
    for (const e of view.edges) {
      const s = byKey.get(e.source);
      const t = byKey.get(e.target);
      if (!s || !t || s.key === t.key) continue;
      add(s, t);
      add(t, s);
    }
    return new Map([...map].map(([k, m]) => [k, [...m.values()]]));
  }, [view]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = view.nodes.filter((n) => !q || n.label.toLowerCase().includes(q) || (n.path ?? "").toLowerCase().includes(q));
    const byName = (a: GraphNode, b: GraphNode) => a.label.localeCompare(b.label);
    return [...list].sort((a, b) => {
      // Search matches first, so "results highlighted in the graph" carries over to the list.
      const h = Number(highlightKeys.has(b.key)) - Number(highlightKeys.has(a.key));
      if (h !== 0) return h;
      if (sort === "name") return byName(a, b);
      if (sort === "type") return a.ref.kind.localeCompare(b.ref.kind) || byName(a, b);
      return b.degree - a.degree || byName(a, b);
    });
  }, [view.nodes, query, sort, highlightKeys]);

  return (
    <section className="list-view" aria-labelledby={`${filterId}-title`}>
      <div className="list-view-head">
        <h2 id={`${filterId}-title`} className="section-title">
          {view.center ? "Local graph as a list" : "Graph as a list"}
        </h2>
        <div className="list-view-tools">
          <label className="field-inline">
            <span>Find</span>
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by name" />
          </label>
          <label className="field-inline">
            <span>Sort by</span>
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              <option value="connections">Connections</option>
              <option value="name">Name</option>
              <option value="type">Type</option>
            </select>
          </label>
        </div>
      </div>
      <p className="muted small" aria-live="polite">
        {rows.length} of {view.nodes.length} nodes
        {highlightKeys.size > 0 ? ` · ${highlightKeys.size} search matches listed first` : ""}
      </p>
      <div className="table-scroll">
        <table className="node-table">
          <caption className="sr-only">
            Nodes in the current graph view with their type, theme and connections
          </caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Type</th>
              <th scope="col">Theme</th>
              <th scope="col">Connections</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => {
              const cluster = n.cluster_id ? clusterLabel.get(n.cluster_id) : undefined;
              const nbs = neighbors.get(n.key) ?? [];
              const selected = n.key === selectedKey;
              return (
                <tr key={n.key} className={selected ? "is-selected" : highlightKeys.has(n.key) ? "is-match" : undefined} aria-current={selected ? "true" : undefined}>
                  <th scope="row">
                    <button type="button" className="link-btn" onClick={() => onSelect(n.key, n.label)}>
                      {n.label}
                    </button>
                    {highlightKeys.has(n.key) && <span className="badge badge-accent">match</span>}
                    {n.key === view.center && <span className="badge">center</span>}
                    {n.path && <div className="muted small mono">{n.path}</div>}
                  </th>
                  <td>
                    {KIND_LABEL[n.ref.kind]}
                    {n.topic_kind ? <span className="muted"> · {n.topic_kind}</span> : null}
                  </td>
                  <td>
                    {cluster ? (
                      <span className="cluster-chip">
                        <span className="swatch" style={{ background: cluster.color }} aria-hidden="true" />
                        {cluster.label ?? "Unlabelled theme"}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    <span className="sr-only">{n.degree} connections: </span>
                    <span aria-hidden="true" className="degree">{n.degree}</span>{" "}
                    {nbs.slice(0, 5).map((nb, i) => (
                      <span key={nb.key}>
                        {i > 0 && ", "}
                        <button type="button" className="link-btn subtle" onClick={() => onSelect(nb.key, nb.label)}>
                          {nb.label}
                        </button>
                      </span>
                    ))}
                    {nbs.length > 5 && <span className="muted"> and {nbs.length - 5} more</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
