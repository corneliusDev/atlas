import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { JobsStatusResponse } from "../api/types";

export interface UseJobsOptions {
  /** Poll interval while jobs are pending or running. */
  activeIntervalMs?: number;
  /** Poll interval while idle (catches vault scans started elsewhere); 0 disables. */
  idleIntervalMs?: number;
}

/**
 * Progress tray data (UP-4): polls GET /api/jobs/status quickly while work is in flight and
 * slowly (or not at all) when the queue is idle. `kick()` restarts fast polling after an upload.
 */
export function useJobs({ activeIntervalMs = 1000, idleIntervalMs = 10_000 }: UseJobsOptions = {}) {
  const [status, setStatus] = useState<JobsStatusResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [active, setActive] = useState(false);
  const mounted = useRef(true);

  const poll = useCallback(async () => {
    try {
      const s = await api.jobsStatus();
      if (!mounted.current) return;
      setStatus(s);
      setError(null);
      setActive(!s.idle);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e : new Error(String(e)));
      setActive(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void poll();
    return () => {
      mounted.current = false;
    };
  }, [poll]);

  useEffect(() => {
    const interval = active ? activeIntervalMs : idleIntervalMs;
    if (interval <= 0) return;
    const id = window.setInterval(() => void poll(), interval);
    return () => window.clearInterval(id);
  }, [active, activeIntervalMs, idleIntervalMs, poll]);

  const kick = useCallback(() => {
    setActive(true);
    void poll();
  }, [poll]);

  return { status, error, active, kick };
}
