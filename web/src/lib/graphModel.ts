/**
 * Pure translation from the API's GraphView into a graphology graph with Sigma display
 * attributes (GR-2): node size by degree, colour by cluster, edge thickness by score, ghost
 * nodes grey and dashed. No WebGL here, so it is unit-tested directly.
 */
import Graph from "graphology";
import type { GraphEdge, GraphNode, GraphView } from "../api/types";

export interface GraphPalette {
  topic: string;
  ghost: string;
  unclustered: string;
  edgeSemantic: string;
  edgeConfirmed: string;
  edgeWiki: string;
  edgeTopic: string;
  edgeManual: string;
}

export const LIGHT_PALETTE: GraphPalette = {
  topic: "#8a7f72",
  ghost: "#a3a3a3",
  unclustered: "#7d8b99",
  edgeSemantic: "#b9c2cc",
  edgeConfirmed: "#2f7f6f",
  edgeWiki: "#8f99a3",
  edgeTopic: "#ddd6cc",
  edgeManual: "#2f7f6f",
};

export const DARK_PALETTE: GraphPalette = {
  topic: "#b9ad9f",
  ghost: "#6f6f6f",
  unclustered: "#9aa8b5",
  edgeSemantic: "#3d4652",
  edgeConfirmed: "#5fbfa9",
  edgeWiki: "#5c6773",
  edgeTopic: "#363029",
  edgeManual: "#5fbfa9",
};

export interface NodeAttrs {
  label: string;
  x: number;
  y: number;
  size: number;
  color: string;
  type: "circle" | "ghost";
  kind: GraphNode["ref"]["kind"];
  summary: string | null;
  clusterId: string | null;
  topicKind: GraphNode["topic_kind"];
  degree: number;
}

export interface EdgeAttrs {
  size: number;
  color: string;
  kind: GraphEdge["kind"];
  weight: number;
  reason: string | null;
  feedback: GraphEdge["feedback"];
}

export type AtlasGraph = Graph<NodeAttrs, EdgeAttrs>;

/** 4px for isolated nodes, growing with sqrt(degree), capped so hubs stay readable. */
export function nodeSize(node: Pick<GraphNode, "degree" | "ref">): number {
  const base = node.ref.kind === "document" ? 4 : node.ref.kind === "topic" ? 3.5 : 3;
  return Math.min(22, base + Math.sqrt(Math.max(0, node.degree)) * 2.2);
}

/** Semantic edges: 0.5px at score 0.5 up to 5px at 1.0. Wiki/manual fixed; topic edges thin. */
export function edgeSize(edge: Pick<GraphEdge, "kind" | "weight">): number {
  switch (edge.kind) {
    case "semantic":
      return Math.max(0.5, Math.min(5, 0.5 + (edge.weight - 0.5) * 9));
    case "manual":
      return 2.5;
    case "wiki":
      return 1.2;
    case "topic":
      return 0.4 + edge.weight * 0.8;
  }
}

export function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic pseudo-random in [0, 1) from a key, so layouts start the same every load. */
const rand = (key: string, salt: number) => (hashString(`${key}#${salt}`) % 10_000) / 10_000;

export function buildGraph(
  view: GraphView,
  palette: GraphPalette,
  previous?: ReadonlyMap<string, { x: number; y: number }>,
): AtlasGraph {
  const graph: AtlasGraph = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });
  const clusterColor = new Map(view.clusters.map((c) => [c.id, c.color]));
  const clusterIndex = new Map(view.clusters.map((c, i) => [c.id, i]));
  const clusterCount = Math.max(1, view.clusters.length);

  for (const node of view.nodes) {
    const prev = previous?.get(node.key);
    let x: number;
    let y: number;
    if (prev) {
      ({ x, y } = prev);
    } else {
      // Seed each cluster around a circle so ForceAtlas2 settles into themes quickly.
      const ci = node.cluster_id ? (clusterIndex.get(node.cluster_id) ?? -1) : -1;
      const angle = ci >= 0 ? (ci / clusterCount) * Math.PI * 2 : rand(node.key, 1) * Math.PI * 2;
      const radius = ci >= 0 ? 100 : node.ref.kind === "topic" ? 30 : 60;
      x = Math.cos(angle) * radius + (rand(node.key, 2) - 0.5) * 60;
      y = Math.sin(angle) * radius + (rand(node.key, 3) - 0.5) * 60;
    }
    const color =
      node.ref.kind === "ghost"
        ? palette.ghost
        : node.ref.kind === "topic"
          ? palette.topic
          : (node.cluster_id && clusterColor.get(node.cluster_id)) || palette.unclustered;
    graph.addNode(node.key, {
      label: node.label,
      x,
      y,
      size: nodeSize(node),
      color,
      type: node.ref.kind === "ghost" ? "ghost" : "circle",
      kind: node.ref.kind,
      summary: node.summary ?? null,
      clusterId: node.cluster_id ?? null,
      topicKind: node.topic_kind ?? null,
      degree: node.degree,
    });
  }

  for (const edge of view.edges) {
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target) || edge.source === edge.target) continue;
    if (graph.hasEdge(edge.source, edge.target)) {
      // Keep the strongest signal when, e.g., a wiki link and a semantic link join the same pair.
      const existing = graph.edge(edge.source, edge.target)!;
      if (graph.getEdgeAttribute(existing, "kind") === "semantic" || edge.kind !== "semantic") continue;
      graph.dropEdge(existing);
    }
    const color =
      edge.target.startsWith("ghost:")
        ? palette.ghost
        : edge.feedback === "confirmed"
          ? palette.edgeConfirmed
          : edge.kind === "semantic"
            ? palette.edgeSemantic
            : edge.kind === "wiki"
              ? palette.edgeWiki
              : edge.kind === "manual"
                ? palette.edgeManual
                : palette.edgeTopic;
    graph.addEdgeWithKey(edge.key, edge.source, edge.target, {
      size: edgeSize(edge),
      color,
      kind: edge.kind,
      weight: edge.weight,
      reason: edge.reason ?? null,
      feedback: edge.feedback ?? null,
    });
  }
  return graph;
}

/** Splits a document node key into its id, or null for topic/ghost keys. */
export function docIdFromKey(key: string): string | null {
  return key.startsWith("doc:") ? key.slice(4) : null;
}

export const docKey = (id: string) => `doc:${id}`;
