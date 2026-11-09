import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "./api/client";
import type { ClusterInfo, GraphView, IgnoredFile, LinkVerdict, SearchHit, UploadResponse } from "./api/types";
import { Breadcrumbs } from "./components/Breadcrumbs";
import { DocumentPanel } from "./components/DocumentPanel";
import { EvidenceDialog } from "./components/EvidenceDialog";
import { FiltersPanel } from "./components/FiltersPanel";
import { GraphArea } from "./components/graph/GraphArea";
import type { EdgeSelection, FocusRequest } from "./components/graph/GraphCanvas";
import { ListView } from "./components/ListView";
import { NodePanel } from "./components/NodePanel";
import { ProgressTray } from "./components/ProgressTray";
import { SearchPalette } from "./components/SearchPalette";
import { UploadZone, useUpload } from "./components/UploadZone";
import { useAsync } from "./hooks/useAsync";
import { useJobs } from "./hooks/useJobs";
import { useTheme } from "./hooks/useTheme";
import { DEFAULT_FILTERS, filterView, toGraphQuery, type Filters } from "./lib/filters";
import { docIdFromKey, docKey } from "./lib/graphModel";
import { EMPTY_TRAVEL, currentCrumb, travelReducer } from "./lib/travel";

type ViewMode = "graph" | "list";
type Scope = "global" | "local";
type PendingFocus = { type: "cluster"; id: string } | { type: "node"; key: string } | null;

const VIEW_KEY = "atlas.viewMode";

function readViewMode(): ViewMode {
  try {
    return window.localStorage.getItem(VIEW_KEY) === "list" ? "list" : "graph";
  } catch {
    return "graph";
  }
}

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export default function App() {
  const theme = useTheme();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [scope, setScope] = useState<Scope>("global");
  const [depth, setDepth] = useState<1 | 2 | 3>(2);
  const [viewMode, setViewModeState] = useState<ViewMode>(readViewMode);
  const [travel, dispatch] = useReducer(travelReducer, EMPTY_TRAVEL);
  const [panelOpen, setPanelOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [lastQuery, setLastQuery] = useState("");
  const [highlight, setHighlight] = useState<{ query: string; keys: ReadonlySet<string> }>({ query: "", keys: new Set() });
  const [evidence, setEvidence] = useState<{ a: string; b: string } | null>(null);
  const [focus, setFocus] = useState<FocusRequest | null>(null);
  const [pendingFocus, setPendingFocus] = useState<PendingFocus>(null);
  const [version, setVersion] = useState(0);
  const [ignored, setIgnored] = useState<IgnoredFile[]>([]);
  const [trayDismissed, setTrayDismissed] = useState(true);
  const [batchDone, setBatchDone] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const focusNonce = useRef(0);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const setViewMode = (m: ViewMode) => {
    setViewModeState(m);
    try {
      window.localStorage.setItem(VIEW_KEY, m);
    } catch {
      /* storage unavailable */
    }
  };

  const crumb = currentCrumb(travel);
  const selectedKey = crumb?.key ?? null;
  const localCenter = scope === "local" ? selectedKey : null;

  // Unfiltered catalog: every cluster and tag for the filter panel, and the empty-vault check.
  const catalog = useAsync((signal) => api.graph({ layers: ["document"] }, signal), [version]);
  const view = useAsync<GraphView>(
    (signal) =>
      localCenter
        ? api.localGraph(localCenter, depth, undefined, signal).then((v) => filterView(v, filters))
        : api.graph(toGraphQuery(filters), signal),
    [localCenter, depth, filters, version],
  );

  const clusterList = catalog.data?.clusters ?? [];
  const clusters = useMemo(() => new Map<string, ClusterInfo>(clusterList.map((c) => [c.id, c])), [clusterList]);
  const tags = useMemo(() => [...new Set((catalog.data?.nodes ?? []).flatMap((n) => n.tags))].sort(), [catalog.data]);
  const empty = catalog.data !== null && catalog.data.stats.documents === 0;

  // Jobs: refresh the graph as files land so nodes appear live (flow A, step 3).
  const jobs = useJobs();
  const linked = jobs.status?.files.filter((f) => f.status === "linked").length ?? 0;
  const prevLinked = useRef(0);
  useEffect(() => {
    if (linked > prevLinked.current) refresh();
    prevLinked.current = linked;
  }, [linked, refresh]);
  const wasActive = useRef(false);
  useEffect(() => {
    // A vault scan started elsewhere (or at first boot) opens the tray too (flow A, step 2).
    if (jobs.active) setTrayDismissed(false);
    if (wasActive.current && !jobs.active) {
      setBatchDone(true);
      refresh();
    }
    wasActive.current = jobs.active;
  }, [jobs.active, refresh]);

  const onUploaded = useCallback(
    (res: UploadResponse) => {
      setIgnored(res.ignored);
      setTrayDismissed(false);
      setBatchDone(false);
      jobs.kick();
    },
    [jobs],
  );
  const dropUpload = useUpload(onUploaded);

  // Navigation.
  const visit = useCallback((key: string, label: string) => {
    dispatch({ type: "visit", crumb: { key, label } });
    setPanelOpen(true);
  }, []);
  const back = () => {
    dispatch({ type: "back" });
    setPanelOpen(true);
  };
  const forward = () => {
    dispatch({ type: "forward" });
    setPanelOpen(true);
  };
  const relabel = useCallback((key: string, label: string) => dispatch({ type: "relabel", key, label }), []);

  const requestFocus = useCallback((keys: string[]) => {
    if (!keys.length) return;
    focusNonce.current += 1;
    setFocus({ keys, nonce: focusNonce.current });
  }, []);

  // Resolve focus requests once the target nodes are in the current view.
  useEffect(() => {
    if (!pendingFocus || !view.data || view.loading) return;
    const keys =
      pendingFocus.type === "cluster"
        ? view.data.nodes.filter((n) => n.cluster_id === pendingFocus.id && n.ref.kind === "document").map((n) => n.key)
        : view.data.nodes.some((n) => n.key === pendingFocus.key)
          ? [pendingFocus.key]
          : [];
    if (keys.length) requestFocus(keys);
    setPendingFocus(null);
  }, [pendingFocus, view.data, view.loading, requestFocus]);

  // Travelling in global mode keeps the camera on the current node.
  useEffect(() => {
    if (selectedKey) setPendingFocus({ type: "node", key: selectedKey });
  }, [selectedKey]);

  const zoomCluster = (id: string) => {
    setScope("global");
    setViewMode("graph");
    setPendingFocus({ type: "cluster", id });
  };

  const onSearchResults = useCallback((query: string, hits: SearchHit[]) => {
    setLastQuery(query);
    setHighlight({ query, keys: new Set(hits.map((h) => docKey(h.document_id))) });
  }, []);

  const onPick = (hit: SearchHit) => {
    visit(docKey(hit.document_id), hit.title);
    setScope("local");
  };

  const onFeedback = useCallback(
    async (a: string, b: string, verdict: LinkVerdict) => {
      await api.linkFeedback(a, b, verdict);
      refresh();
    },
    [refresh],
  );

  const onSelectEdge = (e: EdgeSelection) => {
    const a = docIdFromKey(e.source);
    const b = docIdFromKey(e.target);
    if (a && b) setEvidence({ a, b });
    else visit(e.target, e.target.replace(/^(topic|ghost):/, ""));
  };

  // Global shortcuts: Cmd/Ctrl+K search, Alt+←/→ travel.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      } else if (e.altKey && e.key === "ArrowLeft") {
        dispatch({ type: "back" });
      } else if (e.altKey && e.key === "ArrowRight") {
        dispatch({ type: "forward" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const summary = useMemo(() => {
    if (!batchDone || !catalog.data) return null;
    const topClusters = [...catalog.data.clusters].sort((x, y) => y.size - x.size).slice(0, 3);
    return { stats: catalog.data.stats, topClusters };
  }, [batchDone, catalog.data]);

  const data = view.data;
  const showPanel = panelOpen && crumb !== null;

  return (
    <div
      className={`app ${showPanel ? "has-panel" : ""} ${filtersOpen && !empty ? "has-filters" : ""}`}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target || !e.relatedTarget) setDragOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        void dropUpload.send([...e.dataTransfer.files]);
      }}
    >
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" className="brand-mark">
            <circle cx="6" cy="7" r="2.6" />
            <circle cx="18" cy="6" r="2" />
            <circle cx="14" cy="18" r="3" />
            <path d="M8 8.5l5 7.5M17.2 8l-2.4 7.2M8.5 6.8l7.6-.6" />
          </svg>
          <h1 className="brand-name">Atlas</h1>
        </div>

        <button type="button" className="search-trigger" onClick={() => setPaletteOpen(true)} aria-keyshortcuts={isMac ? "Meta+K" : "Control+K"}>
          <span aria-hidden="true">⌕</span>
          <span className="grow">{lastQuery ? lastQuery : "Search notes"}</span>
          <kbd>{isMac ? "⌘K" : "Ctrl K"}</kbd>
        </button>

        <div className="topbar-actions">
          {!empty && (
            <>
              <div className="segmented" role="group" aria-label="Graph scope">
                <button type="button" aria-pressed={scope === "global"} onClick={() => setScope("global")}>
                  Global
                </button>
                <button
                  type="button"
                  aria-pressed={scope === "local"}
                  disabled={!selectedKey}
                  title={selectedKey ? "Show the selected node and its neighbours" : "Select a node first"}
                  onClick={() => setScope("local")}
                >
                  Local
                </button>
              </div>
              <div className="segmented" role="group" aria-label="Display">
                <button type="button" aria-pressed={viewMode === "graph"} onClick={() => setViewMode("graph")}>
                  Graph
                </button>
                <button type="button" aria-pressed={viewMode === "list"} onClick={() => setViewMode("list")}>
                  List
                </button>
              </div>
              <button
                type="button"
                className="icon-btn"
                aria-pressed={filtersOpen}
                aria-label={filtersOpen ? "Hide filters" : "Show filters"}
                title="Filters"
                onClick={() => setFiltersOpen((o) => !o)}
              >
                ☰
              </button>
              <UploadZone variant="button" onUploaded={onUploaded} />
            </>
          )}
          <button
            type="button"
            className="icon-btn"
            onClick={theme.toggle}
            aria-label={theme.resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            title="Toggle theme"
          >
            {theme.resolved === "dark" ? "☀" : "☾"}
          </button>
        </div>
      </header>

      {!empty && (
        <Breadcrumbs
          travel={travel}
          onBack={back}
          onForward={forward}
          onJump={(index) => {
            dispatch({ type: "jump", index });
            setPanelOpen(true);
          }}
          onClear={() => {
            dispatch({ type: "clear" });
            setScope("global");
            setPanelOpen(false);
          }}
        />
      )}

      <div className="workspace">
        {filtersOpen && !empty && (
          <FiltersPanel
            filters={filters}
            onChange={setFilters}
            clusters={clusterList}
            tags={tags}
            mode={localCenter ? "local" : "global"}
            depth={depth}
            onDepthChange={setDepth}
            onZoomCluster={zoomCluster}
          />
        )}

        <main id="main" className="stage" aria-busy={view.loading}>
          {catalog.error && !catalog.data ? (
            <div className="stage-message" role="alert">
              <h2>Atlas cannot reach its API</h2>
              <p className="muted">{catalog.error.message}. Check that the api service is running, then reload.</p>
            </div>
          ) : empty ? (
            <div className="empty-state">
              <UploadZone variant="hero" onUploaded={onUploaded} />
            </div>
          ) : data ? (
            <>
              {highlight.keys.size > 0 && (
                <div className="match-bar" role="status">
                  <span>
                    {highlight.keys.size} {highlight.keys.size === 1 ? "match" : "matches"} for “{highlight.query}” highlighted
                  </span>
                  <button type="button" className="link-btn small" onClick={() => onSearchResults("", [])}>
                    Clear
                  </button>
                </div>
              )}
              {viewMode === "list" ? (
                <ListView view={data} selectedKey={selectedKey} highlightKeys={highlight.keys} onSelect={visit} />
              ) : (
                <GraphArea
                  view={data}
                  theme={theme.resolved}
                  selectedKey={selectedKey}
                  highlightKeys={highlight.keys}
                  focus={focus}
                  onSelectNode={visit}
                  onSelectEdge={onSelectEdge}
                  onShowList={() => setViewMode("list")}
                />
              )}
              <p className="stage-stats muted small">
                {localCenter ? `Local graph · depth ${depth} · ` : ""}
                {data.stats.documents} documents · {data.stats.clusters} themes · {data.stats.links} links
                {view.loading ? " · updating…" : ""}
              </p>
            </>
          ) : view.error ? (
            <div className="stage-message" role="alert">
              <h2>Could not load the graph</h2>
              <p className="muted">{view.error.message}</p>
            </div>
          ) : (
            <div className="stage-message" aria-busy="true">
              <p className="muted">Loading your map…</p>
            </div>
          )}
        </main>

        {showPanel && crumb && (
          <aside className="side-panel" aria-label="Selection details">
            <div className="side-panel-bar">
              {localCenter !== crumb.key && (
                <button
                  type="button"
                  className="link-btn small"
                  onClick={() => setScope("local")}
                >
                  Show local graph
                </button>
              )}
              <span className="grow" />
              <button type="button" className="icon-btn" onClick={() => setPanelOpen(false)} aria-label="Close panel">
                ×
              </button>
            </div>
            <div className="side-panel-body">
              {docIdFromKey(crumb.key) ? (
                <DocumentPanel
                  id={docIdFromKey(crumb.key)!}
                  clusters={clusters}
                  onOpen={visit}
                  onWhy={(a, b) => setEvidence({ a, b })}
                  onFeedback={onFeedback}
                  onLoaded={relabel}
                  version={version}
                />
              ) : (
                <NodePanel nodeKey={crumb.key} label={crumb.label} onOpen={visit} onLoaded={relabel} />
              )}
            </div>
          </aside>
        )}
      </div>

      {!trayDismissed && (
        <ProgressTray
          status={jobs.status}
          ignored={ignored}
          summary={summary}
          onDismiss={() => {
            setTrayDismissed(true);
            setIgnored([]);
          }}
          onOpenDocument={(id, label) => visit(docKey(id), label)}
          onZoomCluster={zoomCluster}
        />
      )}

      {dragOver && (
        <div className="drop-overlay" aria-hidden="true">
          <div className="drop-overlay-card">
            <strong>Drop your .md files here</strong>
            <span className="muted small">or a zipped folder</span>
          </div>
        </div>
      )}
      {dropUpload.error && (
        <p role="alert" className="toast error">
          Upload failed: {dropUpload.error}
        </p>
      )}

      {paletteOpen && (
        <SearchPalette
          initialQuery={lastQuery}
          clusters={clusters}
          onClose={() => setPaletteOpen(false)}
          onResults={onSearchResults}
          onPick={onPick}
        />
      )}
      {evidence && (
        <EvidenceDialog a={evidence.a} b={evidence.b} onClose={() => setEvidence(null)} onFeedback={onFeedback} onOpen={visit} />
      )}
    </div>
  );
}
