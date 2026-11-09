import { useEffect, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

/**
 * Runs `fn` whenever `deps` change, aborting the previous request. Keeps the last good data
 * while a new request is in flight so the graph does not flash empty between filter changes.
 */
export function useAsync<T>(fn: ((signal: AbortSignal) => Promise<T>) | null, deps: readonly unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, loading: fn !== null });

  useEffect(() => {
    if (!fn) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    fn(ctrl.signal).then(
      (data) => {
        if (!ctrl.signal.aborted) setState({ data, error: null, loading: false });
      },
      (error: unknown) => {
        if (ctrl.signal.aborted) return;
        setState((s) => ({ ...s, error: error instanceof Error ? error : new Error(String(error)), loading: false }));
      },
    );
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
