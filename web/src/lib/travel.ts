/** GR-6 travel mode: a breadcrumb trail of visited nodes with browser-style back/forward. */

export interface Crumb {
  key: string;
  label: string;
}

export interface TravelState {
  trail: Crumb[];
  index: number; // -1 when nothing is selected
}

export type TravelAction =
  | { type: "visit"; crumb: Crumb }
  | { type: "back" }
  | { type: "forward" }
  | { type: "jump"; index: number }
  | { type: "clear" }
  | { type: "relabel"; key: string; label: string };

export const EMPTY_TRAVEL: TravelState = { trail: [], index: -1 };
export const MAX_TRAIL = 50;

export function travelReducer(state: TravelState, action: TravelAction): TravelState {
  switch (action.type) {
    case "visit": {
      const current = state.trail[state.index];
      if (current?.key === action.crumb.key) return state;
      const trail = [...state.trail.slice(0, state.index + 1), action.crumb].slice(-MAX_TRAIL);
      return { trail, index: trail.length - 1 };
    }
    case "back":
      return state.index > 0 ? { ...state, index: state.index - 1 } : state;
    case "forward":
      return state.index < state.trail.length - 1 ? { ...state, index: state.index + 1 } : state;
    case "jump":
      return action.index >= 0 && action.index < state.trail.length ? { ...state, index: action.index } : state;
    case "clear":
      return EMPTY_TRAVEL;
    case "relabel":
      return {
        ...state,
        trail: state.trail.map((c) => (c.key === action.key && c.label !== action.label ? { ...c, label: action.label } : c)),
      };
  }
}

export const currentCrumb = (s: TravelState): Crumb | null => s.trail[s.index] ?? null;
export const canGoBack = (s: TravelState) => s.index > 0;
export const canGoForward = (s: TravelState) => s.index < s.trail.length - 1;
