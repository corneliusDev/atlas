import { useCallback, useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const KEY = "atlas.theme";

function readPref(): ThemePref {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Light/dark theme: follows the OS by default; an explicit choice is remembered per browser. */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readPref);
  const [system, setSystem] = useState<ResolvedTheme>(systemTheme);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = () => setSystem(mq.matches ? "dark" : "light");
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  const resolved: ResolvedTheme = pref === "system" ? system : pref;

  useEffect(() => {
    const root = document.documentElement;
    if (pref === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", pref);
    try {
      if (pref === "system") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, pref);
    } catch {
      /* storage unavailable */
    }
  }, [pref]);

  const toggle = useCallback(() => setPref(resolved === "dark" ? "light" : "dark"), [resolved]);

  return { pref, resolved, setPref, toggle };
}
