import type { GraphQuery, GraphView, NodeKind } from "../api/types";

/** GR-5 filters as the UI holds them. */
export interface Filters {
  clusters: string[];
  tags: string[];
  minScore: number;
  showTopics: boolean;
  showGhosts: boolean;
}

export const DEFAULT_FILTERS: Filters = {
  clusters: [],
  tags: [],
  minScore: 0,
  showTopics: true,
  showGhosts: true,
};

export function isFiltered(f: Filters): boolean {
  return f.clusters.length > 0 || f.tags.length > 0 || f.minScore > 0 || !f.showTopics || !f.showGhosts;
}

export function layersFor(f: Filters): NodeKind[] {
  const layers: NodeKind[] = ["document"];
  if (f.showTopics) layers.push("topic");
  if (f.showGhosts) layers.push("ghost");
  return layers;
}

/** Global graph: filters go to the server as query params. */
export function toGraphQuery(f: Filters): GraphQuery {
  return {
    layers: layersFor(f),
    tags: f.tags,
    clusters: f.clusters,
    minScore: f.minScore,
  };
}

/**
 * Local graph: the route takes only a center and depth, so filters apply client-side.
 * The center node is always kept; topic/ghost nodes are dropped once they lose every edge.
 */
export function filterView(view: GraphView, f: Filters): GraphView {
  const center = view.center ?? null;
  const layers = new Set(layersFor(f));
  const clusters = new Set(f.clusters);
  const tags = new Set(f.tags);
  const keep = new Set<string>();
  for (const n of view.nodes) {
    if (n.key === center) {
      keep.add(n.key);
      continue;
    }
    if (!layers.has(n.ref.kind)) continue;
    if (n.ref.kind === "document") {
      if (clusters.size && !(n.cluster_id && clusters.has(n.cluster_id))) continue;
      if (tags.size && !n.tags.some((t) => tags.has(t))) continue;
    }
    keep.add(n.key);
  }
  const edges = view.edges.filter(
    (e) => keep.has(e.source) && keep.has(e.target) && !(e.kind === "semantic" && e.weight < f.minScore),
  );
  const degree = new Map<string, number>();
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  const nodes = view.nodes
    .filter((n) => keep.has(n.key) && (n.ref.kind === "document" || n.key === center || (degree.get(n.key) ?? 0) > 0))
    .map((n) => ({ ...n, degree: degree.get(n.key) ?? 0 }));
  const docs = nodes.filter((n) => n.ref.kind === "document");
  const clusterIds = new Set(docs.map((n) => n.cluster_id).filter(Boolean));
  return {
    ...view,
    nodes,
    edges,
    clusters: view.clusters.filter((c) => clusterIds.has(c.id)),
    stats: {
      documents: docs.length,
      topics: nodes.filter((n) => n.ref.kind === "topic").length,
      clusters: clusterIds.size,
      links: edges.filter((e) => e.kind === "semantic" || e.kind === "manual" || (e.kind === "wiki" && e.target.startsWith("doc:"))).length,
    },
  };
}
