import { canGoBack, canGoForward, type TravelState } from "../lib/travel";

interface Props {
  travel: TravelState;
  onBack: () => void;
  onForward: () => void;
  onJump: (index: number) => void;
  onClear: () => void;
}

/** GR-6 travel trail: Doc A › topic "pricing" › Doc F, with back/forward (Alt+←/→). */
export function Breadcrumbs({ travel, onBack, onForward, onJump, onClear }: Props) {
  if (travel.trail.length === 0) return null;
  return (
    <nav className="breadcrumbs" aria-label="Travel path">
      <button type="button" className="icon-btn" onClick={onBack} disabled={!canGoBack(travel)} aria-label="Back" title="Back (Alt+←)">
        ←
      </button>
      <button type="button" className="icon-btn" onClick={onForward} disabled={!canGoForward(travel)} aria-label="Forward" title="Forward (Alt+→)">
        →
      </button>
      <ol>
        {travel.trail.map((c, i) => (
          <li key={`${c.key}-${i}`} className={i > travel.index ? "is-ahead" : undefined}>
            <button type="button" className="crumb" aria-current={i === travel.index ? "location" : undefined} onClick={() => onJump(i)}>
              {c.key.startsWith("topic:") ? <span className="crumb-kind">topic</span> : null}
              {c.key.startsWith("ghost:") ? <span className="crumb-kind">unwritten</span> : null}
              {c.label}
            </button>
          </li>
        ))}
      </ol>
      <button type="button" className="link-btn small" onClick={onClear}>
        Clear path
      </button>
    </nav>
  );
}
