/**
 * WebGL graph (GR-1..GR-3, GR-7): Sigma.js renders a graphology graph; ForceAtlas2 runs in a
 * web worker. Loaded lazily and only when WebGL is available (see GraphArea), because sigma
 * touches WebGLRenderingContext at import time.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import { NodeCircleProgram } from "sigma/rendering";
import type { NodeDisplayData, PartialButFor } from "sigma/types";
import type { Settings } from "sigma/settings";
import forceAtlas2 from "graphology-layout-forceatlas2";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import type { GraphView } from "../../api/types";
import type { ResolvedTheme } from "../../hooks/useTheme";
import { DARK_PALETTE, LIGHT_PALETTE, buildGraph, type AtlasGraph, type EdgeAttrs, type NodeAttrs } from "../../lib/graphModel";
import { NodeDashedProgram } from "./NodeDashedProgram";

export interface FocusRequest {
  keys: string[];
  nonce: number;
}

export interface EdgeSelection {
  key: string;
  kind: EdgeAttrs["kind"];
  source: string;
  target: string;
}

export interface GraphCanvasProps {
  view: GraphView;
  theme: ResolvedTheme;
  selectedKey: string | null;
  highlightKeys: ReadonlySet<string>;
  focus: FocusRequest | null;
  onSelectNode: (key: string, label: string) => void;
  onSelectEdge: (edge: EdgeSelection) => void;
}

interface Tooltip {
  key: string;
  x: number;
  y: number;
  label: string;
  summary: string | null;
  kind: NodeAttrs["kind"];
  topicKind: NodeAttrs["topicKind"];
}

const THEME = {
  light: { label: "#2b2a28", dim: "#e7e3dd", dimEdge: "#efebe5", hoverBg: "#fffdf9", hoverText: "#2b2a28" },
  dark: { label: "#e6e3de", dim: "#2c2f33", dimEdge: "#24272b", hoverBg: "#202326", hoverText: "#eeeae4" },
} as const;

function makeHoverRenderer(theme: ResolvedTheme) {
  const t = THEME[theme];
  return (
    context: CanvasRenderingContext2D,
    data: PartialButFor<NodeDisplayData, "x" | "y" | "size" | "label" | "color">,
    settings: Settings,
  ) => {
    const size = settings.labelSize;
    context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`;
    const label = data.label ?? "";
    const w = context.measureText(label).width + 12;
    const h = size + 10;
    context.fillStyle = t.hoverBg;
    context.shadowColor = "rgba(0,0,0,0.18)";
    context.shadowBlur = 8;
    context.beginPath();
    context.arc(data.x, data.y, data.size + 3, 0, Math.PI * 2);
    context.fill();
    if (label) {
      const x = data.x + data.size + 4;
      context.beginPath();
      context.roundRect(x, data.y - h / 2, w, h, 4);
      context.fill();
      context.shadowBlur = 0;
      context.fillStyle = t.hoverText;
      context.fillText(label, x + 6, data.y + size / 3);
    }
    context.shadowBlur = 0;
  };
}

export default function GraphCanvas(props: GraphCanvasProps) {
  const { view, theme, selectedKey, highlightKeys, focus } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma<NodeAttrs, EdgeAttrs> | null>(null);
  const graphRef = useRef<AtlasGraph | null>(null);
  const layoutRef = useRef<FA2Layout | null>(null);
  const layoutTimer = useRef<number | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;
  const lastFocus = useRef<FocusRequest | null>(null);
  const interaction = useRef({
    hovered: null as string | null,
    hoverNeighbors: new Set<string>(),
    selected: null as string | null,
    highlights: new Set<string>() as ReadonlySet<string>,
    theme: theme as ResolvedTheme,
    dragging: null as string | null,
    dragMoved: false,
  });
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);
  const [layoutRunning, setLayoutRunning] = useState(false);

  const stopLayout = useCallback(() => {
    if (layoutTimer.current !== null) window.clearTimeout(layoutTimer.current);
    layoutTimer.current = null;
    layoutRef.current?.kill();
    layoutRef.current = null;
    setLayoutRunning(false);
  }, []);

  const focusOn = useCallback((keys: string[], animate = true) => {
    const sigma = sigmaRef.current;
    const graph = graphRef.current;
    if (!sigma || !graph) return;
    const pts = keys.filter((k) => graph.hasNode(k)).map((k) => sigma.getNodeDisplayData(k)).filter((d): d is NodeDisplayData => !!d);
    if (!pts.length) return;
    const x = pts.reduce((s, p) => s + p.x, 0) / pts.length;
    const y = pts.reduce((s, p) => s + p.y, 0) / pts.length;
    const spread = Math.max(...pts.map((p) => Math.hypot(p.x - x, p.y - y)));
    const ratio = pts.length === 1 ? 0.45 : Math.min(1, Math.max(0.2, spread * 2.6));
    sigma.getCamera().animate({ x, y, ratio }, { duration: animate ? 600 : 0 });
  }, []);

  const runLayout = useCallback(
    (durationMs: number) => {
      const graph = graphRef.current;
      if (!graph || graph.order < 2) return;
      stopLayout();
      try {
        const settings = { ...forceAtlas2.inferSettings(graph), barnesHutOptimize: graph.order > 400, slowDown: 4 };
        const layout = new FA2Layout(graph, { settings, getEdgeWeight: "weight" });
        layoutRef.current = layout;
        layout.start();
        setLayoutRunning(true);
        layoutTimer.current = window.setTimeout(() => {
          stopLayout();
          if (lastFocus.current) focusOn(lastFocus.current.keys);
        }, durationMs);
      } catch {
        // Workers unavailable: keep the seeded positions.
        setLayoutRunning(false);
      }
    },
    [focusOn, stopLayout],
  );

  // Mount sigma once.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const graph: AtlasGraph = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });
    graphRef.current = graph;
    const st = interaction.current;
    const sigma = new Sigma<NodeAttrs, EdgeAttrs>(graph, container, {
      nodeProgramClasses: { circle: NodeCircleProgram, ghost: NodeDashedProgram },
      defaultNodeType: "circle",
      enableEdgeEvents: true,
      zIndex: true,
      labelFont: "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
      labelSize: 12,
      labelWeight: "500",
      labelDensity: 0.9,
      labelRenderedSizeThreshold: 7,
      labelColor: { color: THEME[theme].label },
      defaultDrawNodeHover: makeHoverRenderer(theme),
      minCameraRatio: 0.05,
      maxCameraRatio: 4,
      nodeReducer: (node, data) => {
        const res: Partial<NodeDisplayData> = { ...data };
        const t = THEME[st.theme];
        const hl = st.highlights;
        if (hl.size > 0) {
          if (hl.has(node)) {
            res.highlighted = true;
            res.zIndex = 2;
            res.size = data.size * 1.3;
            res.forceLabel = true;
          } else if (node !== st.selected) {
            res.color = t.dim;
            res.label = "";
            res.zIndex = 0;
          }
        }
        if (st.hovered && node !== st.hovered && !st.hoverNeighbors.has(node)) {
          res.color = t.dim;
          res.label = "";
          res.zIndex = 0;
        }
        if (node === st.selected) {
          res.highlighted = true;
          res.forceLabel = true;
          res.zIndex = 3;
        }
        return res;
      },
      edgeReducer: (edge, data) => {
        const res = { ...data } as Partial<typeof data> & { hidden?: boolean; zIndex?: number };
        const t = THEME[st.theme];
        const [s, tg] = graph.extremities(edge);
        if (st.hovered) {
          if (s !== st.hovered && tg !== st.hovered) res.color = t.dimEdge;
          else res.zIndex = 2;
        } else if (st.highlights.size > 0 && !st.highlights.has(s) && !st.highlights.has(tg)) {
          res.color = t.dimEdge;
        } else if (st.selected && (s === st.selected || tg === st.selected)) {
          res.zIndex = 1;
        }
        return res;
      },
    });
    sigmaRef.current = sigma;

    const showTooltip = (node: string) => {
      const attrs = graph.getNodeAttributes(node);
      const pos = sigma.graphToViewport({ x: attrs.x, y: attrs.y });
      setTooltip({ key: node, x: pos.x, y: pos.y, label: attrs.label, summary: attrs.summary, kind: attrs.kind, topicKind: attrs.topicKind });
    };

    sigma.on("enterNode", ({ node }) => {
      st.hovered = node;
      st.hoverNeighbors = new Set(graph.neighbors(node));
      container.style.cursor = "pointer";
      showTooltip(node);
      sigma.refresh({ skipIndexation: true });
    });
    sigma.on("leaveNode", () => {
      st.hovered = null;
      st.hoverNeighbors = new Set();
      container.style.cursor = "";
      setTooltip(null);
      sigma.refresh({ skipIndexation: true });
    });
    sigma.on("enterEdge", () => {
      container.style.cursor = "pointer";
    });
    sigma.on("leaveEdge", () => {
      container.style.cursor = "";
    });
    sigma.on("downNode", ({ node }) => {
      st.dragging = node;
      st.dragMoved = false;
      if (!sigma.getCustomBBox()) sigma.setCustomBBox(sigma.getBBox());
    });
    sigma.getMouseCaptor().on("mousemovebody", (e) => {
      if (!st.dragging) return;
      if (!st.dragMoved) {
        st.dragMoved = true;
        stopLayout();
      }
      const pos = sigma.viewportToGraph(e);
      graph.setNodeAttribute(st.dragging, "x", pos.x);
      graph.setNodeAttribute(st.dragging, "y", pos.y);
      if (st.hovered === st.dragging) showTooltip(st.dragging);
      e.preventSigmaDefault();
      e.original.preventDefault();
      e.original.stopPropagation();
    });
    sigma.getMouseCaptor().on("mouseup", () => {
      st.dragging = null;
    });
    sigma.on("clickNode", ({ node }) => {
      if (st.dragMoved) {
        st.dragMoved = false;
        return;
      }
      callbacks.current.onSelectNode(node, graph.getNodeAttribute(node, "label"));
    });
    sigma.on("clickEdge", ({ edge }) => {
      const [source, target] = graph.extremities(edge);
      callbacks.current.onSelectEdge({ key: edge, kind: graph.getEdgeAttribute(edge, "kind"), source, target });
    });
    sigma.getCamera().on("updated", () => {
      if (st.hovered && graph.hasNode(st.hovered)) showTooltip(st.hovered);
    });

    return () => {
      stopLayout();
      sigma.kill();
      sigmaRef.current = null;
      graphRef.current = null;
    };
    // Mounted once; theme and data are applied by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Theme: label colour and hover renderer.
  useEffect(() => {
    interaction.current.theme = theme;
    const sigma = sigmaRef.current;
    if (!sigma) return;
    sigma.setSetting("labelColor", { color: THEME[theme].label });
    sigma.setSetting("defaultDrawNodeHover", makeHoverRenderer(theme));
  }, [theme]);

  // Data: rebuild the graph, keeping positions of nodes we already placed.
  useEffect(() => {
    const graph = graphRef.current;
    const sigma = sigmaRef.current;
    if (!graph || !sigma) return;
    const previous = new Map<string, { x: number; y: number }>();
    graph.forEachNode((key, attrs) => previous.set(key, { x: attrs.x, y: attrs.y }));
    const next = buildGraph(view, theme === "dark" ? DARK_PALETTE : LIGHT_PALETTE, previous);
    const newNodes = next.filterNodes((key) => !previous.has(key)).length;
    stopLayout();
    graph.clear();
    graph.import(next.export());
    sigma.setCustomBBox(null);
    setTooltip(null);
    interaction.current.hovered = null;
    interaction.current.hoverNeighbors = new Set();
    if (newNodes > 0) runLayout(Math.min(6000, 1500 + graph.order * 6));
    sigma.refresh();
  }, [view, theme, runLayout, stopLayout]);

  // Selection and search highlights.
  useEffect(() => {
    interaction.current.selected = selectedKey;
    interaction.current.highlights = highlightKeys;
    sigmaRef.current?.refresh({ skipIndexation: true });
  }, [selectedKey, highlightKeys]);

  // Camera focus requests (search pick, cluster zoom, travel).
  useEffect(() => {
    if (!focus || focus === lastFocus.current) return;
    lastFocus.current = focus;
    // Let the data effect place new nodes first.
    const id = window.setTimeout(() => focusOn(focus.keys), 50);
    return () => window.clearTimeout(id);
  }, [focus, focusOn]);

  const camera = (fn: "zoomIn" | "zoomOut" | "reset") => {
    const cam = sigmaRef.current?.getCamera();
    if (!cam) return;
    if (fn === "zoomIn") void cam.animatedZoom({ duration: 250 });
    else if (fn === "zoomOut") void cam.animatedUnzoom({ duration: 250 });
    else {
      lastFocus.current = null;
      void cam.animatedReset({ duration: 400 });
    }
  };

  const docs = view.stats.documents;
  return (
    <div className="graph-canvas-wrap">
      <div
        ref={containerRef}
        className="graph-canvas"
        role="img"
        aria-label={`Graph of ${docs} documents, ${view.stats.topics} topics and ${view.stats.links} links. Use the list view for keyboard and screen reader access.`}
      />
      {tooltip && (
        <div className="graph-tooltip" style={{ left: tooltip.x, top: tooltip.y }} role="tooltip">
          <div className="graph-tooltip-title">{tooltip.label}</div>
          {tooltip.kind === "document" && <p>{tooltip.summary ?? "Summary pending."}</p>}
          {tooltip.kind === "topic" && <p className="muted">Topic{tooltip.topicKind ? ` · ${tooltip.topicKind}` : ""}</p>}
          {tooltip.kind === "ghost" && <p className="muted">Linked but not written yet</p>}
        </div>
      )}
      <div className="graph-controls" role="toolbar" aria-label="Graph camera">
        <button type="button" className="icon-btn" onClick={() => camera("zoomIn")} aria-label="Zoom in" title="Zoom in">
          +
        </button>
        <button type="button" className="icon-btn" onClick={() => camera("zoomOut")} aria-label="Zoom out" title="Zoom out">
          −
        </button>
        <button type="button" className="icon-btn" onClick={() => camera("reset")} aria-label="Fit graph" title="Fit graph">
          ⤢
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={() => (layoutRunning ? stopLayout() : runLayout(4000))}
          aria-label={layoutRunning ? "Stop layout" : "Re-run layout"}
          title={layoutRunning ? "Stop layout" : "Re-run layout"}
        >
          {layoutRunning ? "■" : "↻"}
        </button>
      </div>
    </div>
  );
}
