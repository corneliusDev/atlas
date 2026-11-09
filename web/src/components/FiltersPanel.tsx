import { useId } from "react";
import type { ClusterInfo } from "../api/types";
import { DEFAULT_FILTERS, isFiltered, type Filters } from "../lib/filters";

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
  clusters: ClusterInfo[];
  tags: string[];
  mode: "global" | "local";
  depth: 1 | 2 | 3;
  onDepthChange: (d: 1 | 2 | 3) => void;
  onZoomCluster?: (clusterId: string) => void;
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** GR-5 filters (cluster, tag, similarity threshold, topic and ghost layers) + GR-4 depth. */
export function FiltersPanel({ filters, onChange, clusters, tags, mode, depth, onDepthChange, onZoomCluster }: Props) {
  const id = useId();
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });

  return (
    <aside className="filters" aria-labelledby={`${id}-title`}>
      <div className="filters-head">
        <h2 id={`${id}-title`} className="section-title">
          Filters
        </h2>
        {isFiltered(filters) && (
          <button type="button" className="link-btn small" onClick={() => onChange(DEFAULT_FILTERS)}>
            Reset
          </button>
        )}
      </div>

      {mode === "local" && (
        <div className="field">
          <label htmlFor={`${id}-depth`} className="field-label">
            Depth <output htmlFor={`${id}-depth`}>{depth}</output>
          </label>
          <input
            id={`${id}-depth`}
            type="range"
            min={1}
            max={3}
            step={1}
            value={depth}
            onChange={(e) => onDepthChange(Number(e.target.value) as 1 | 2 | 3)}
            aria-valuetext={`${depth} ${depth === 1 ? "hop" : "hops"}`}
          />
          <div className="range-scale" aria-hidden="true">
            <span>1</span>
            <span>2</span>
            <span>3</span>
          </div>
        </div>
      )}

      <div className="field">
        <label htmlFor={`${id}-score`} className="field-label">
          Minimum similarity <output htmlFor={`${id}-score`}>{Math.round(filters.minScore * 100)}%</output>
        </label>
        <input
          id={`${id}-score`}
          type="range"
          min={0}
          max={0.95}
          step={0.05}
          value={filters.minScore}
          onChange={(e) => set({ minScore: Number(e.target.value) })}
          aria-valuetext={`${Math.round(filters.minScore * 100)} percent`}
        />
      </div>

      <fieldset className="field">
        <legend className="field-label">Layers</legend>
        <label className="check">
          <input type="checkbox" checked={filters.showTopics} onChange={(e) => set({ showTopics: e.target.checked })} />
          Show topics
        </label>
        <label className="check">
          <input type="checkbox" checked={filters.showGhosts} onChange={(e) => set({ showGhosts: e.target.checked })} />
          Show unwritten notes
        </label>
      </fieldset>

      {clusters.length > 0 && (
        <fieldset className="field">
          <legend className="field-label">Themes</legend>
          <ul className="plain-list">
            {clusters.map((c) => (
              <li key={c.id} className="cluster-row">
                <label className="check">
                  <input type="checkbox" checked={filters.clusters.includes(c.id)} onChange={() => set({ clusters: toggle(filters.clusters, c.id) })} />
                  <span className="swatch" style={{ background: c.color }} aria-hidden="true" />
                  <span className="grow">{c.label ?? "Unlabelled theme"}</span>
                  <span className="muted small">{c.size}</span>
                </label>
                {onZoomCluster && (
                  <button type="button" className="icon-btn small" onClick={() => onZoomCluster(c.id)} aria-label={`Zoom to ${c.label ?? "theme"}`} title="Zoom to theme">
                    ⌖
                  </button>
                )}
              </li>
            ))}
          </ul>
        </fieldset>
      )}

      {tags.length > 0 && (
        <fieldset className="field">
          <legend className="field-label">Tags</legend>
          <div className="tag-cloud">
            {tags.map((t) => {
              const on = filters.tags.includes(t);
              return (
                <button key={t} type="button" className={`tag ${on ? "is-on" : ""}`} aria-pressed={on} onClick={() => set({ tags: toggle(filters.tags, t) })}>
                  #{t}
                </button>
              );
            })}
          </div>
        </fieldset>
      )}
    </aside>
  );
}
