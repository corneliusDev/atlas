import { describe, expect, it } from "vitest";
import { buildGraph, edgeSize, LIGHT_PALETTE, nodeSize } from "../lib/graphModel";
import { DEFAULT_FILTERS, filterView, toGraphQuery } from "../lib/filters";
import { EMPTY_TRAVEL, canGoBack, canGoForward, currentCrumb, travelReducer } from "../lib/travel";
import { ALL_FILTERS, globalGraph, localGraph } from "../mocks/db";
import { SEED_DOCS } from "../mocks/data";

describe("graphModel", () => {
  const view = globalGraph(ALL_FILTERS);

  it("mock graph has ~50 nodes: documents, topics and ghosts", () => {
    expect(view.stats.documents).toBe(SEED_DOCS.length);
    expect(view.nodes.length).toBeGreaterThanOrEqual(45);
    expect(view.nodes.length).toBeLessThanOrEqual(60);
    expect(view.nodes.some((n) => n.ref.kind === "topic")).toBe(true);
    expect(view.nodes.some((n) => n.ref.kind === "ghost")).toBe(true);
  });

  it("sizes nodes by degree and edges by score", () => {
    const doc = { ref: { kind: "document" as const, id: "x" }, degree: 0 };
    expect(nodeSize({ ...doc, degree: 16 })).toBeGreaterThan(nodeSize({ ...doc, degree: 1 }));
    expect(nodeSize({ ...doc, degree: 10_000 })).toBe(22);
    expect(edgeSize({ kind: "semantic", weight: 0.95 })).toBeGreaterThan(edgeSize({ kind: "semantic", weight: 0.6 }));
  });

  it("colours documents by cluster and draws ghosts grey and dashed", () => {
    const g = buildGraph(view, LIGHT_PALETTE);
    const clusterColor = new Map(view.clusters.map((c) => [c.id, c.color]));
    const doc = view.nodes.find((n) => n.ref.kind === "document" && n.cluster_id)!;
    expect(g.getNodeAttribute(doc.key, "color")).toBe(clusterColor.get(doc.cluster_id!));
    const ghost = view.nodes.find((n) => n.ref.kind === "ghost")!;
    expect(g.getNodeAttribute(ghost.key, "color")).toBe(LIGHT_PALETTE.ghost);
    expect(g.getNodeAttribute(ghost.key, "type")).toBe("ghost");
  });

  it("keeps previous positions so the layout does not jump on refresh", () => {
    const key = view.nodes[0]!.key;
    const g = buildGraph(view, LIGHT_PALETTE, new Map([[key, { x: 42, y: -7 }]]));
    expect(g.getNodeAttributes(key)).toMatchObject({ x: 42, y: -7 });
  });
});

describe("filters", () => {
  it("drops the topic layer from the server query when topics are hidden", () => {
    expect(toGraphQuery({ ...DEFAULT_FILTERS, showTopics: false }).layers).toEqual(["document", "ghost"]);
  });

  it("filters a local graph client-side but always keeps the centre", () => {
    const center = globalGraph(ALL_FILTERS).nodes.find((n) => n.ref.kind === "document" && n.degree > 2)!;
    const local = localGraph(center.key, 2)!;
    const filtered = filterView(local, { ...DEFAULT_FILTERS, minScore: 0.99, showTopics: false });
    expect(filtered.nodes.some((n) => n.key === center.key)).toBe(true);
    expect(filtered.nodes.some((n) => n.ref.kind === "topic")).toBe(false);
    expect(filtered.edges.every((e) => e.kind !== "semantic" || e.weight >= 0.99)).toBe(true);
  });
});

describe("travel", () => {
  const a = { key: "doc:a", label: "A" };
  const t = { key: "topic:p", label: "pricing" };
  const f = { key: "doc:f", label: "F" };

  it("records a breadcrumb trail with back and forward", () => {
    let s = [a, t, f].reduce((st, crumb) => travelReducer(st, { type: "visit", crumb }), EMPTY_TRAVEL);
    expect(s.trail.map((c) => c.label)).toEqual(["A", "pricing", "F"]);
    s = travelReducer(s, { type: "back" });
    expect(currentCrumb(s)?.key).toBe("topic:p");
    expect(canGoForward(s)).toBe(true);
    s = travelReducer(s, { type: "forward" });
    expect(currentCrumb(s)?.key).toBe("doc:f");
    expect(canGoForward(s)).toBe(false);
  });

  it("visiting after going back truncates the forward history", () => {
    let s = [a, t, f].reduce((st, crumb) => travelReducer(st, { type: "visit", crumb }), EMPTY_TRAVEL);
    s = travelReducer(travelReducer(s, { type: "back" }), { type: "back" });
    s = travelReducer(s, { type: "visit", crumb: f });
    expect(s.trail.map((c) => c.key)).toEqual(["doc:a", "doc:f"]);
    expect(canGoBack(s)).toBe(true);
  });
});
