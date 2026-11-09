import { Suspense, lazy, useMemo } from "react";
import type { GraphCanvasProps } from "./GraphCanvas";
import { GraphOverlay } from "./GraphOverlay";

const GraphCanvas = lazy(() => import("./GraphCanvas"));

export function hasWebGL(): boolean {
  try {
    if (typeof window === "undefined" || typeof window.WebGLRenderingContext === "undefined") return false;
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

interface Props extends GraphCanvasProps {
  onShowList: () => void;
}

/** Renders the WebGL graph when the browser supports it, otherwise points to the list view. */
export function GraphArea({ onShowList, ...canvas }: Props) {
  const webgl = useMemo(hasWebGL, []);
  if (!webgl) {
    return (
      <div className="graph-fallback" role="status">
        <p>This browser cannot draw the graph (WebGL is unavailable).</p>
        <button type="button" className="btn" onClick={onShowList}>
          Show as list
        </button>
      </div>
    );
  }
  return (
    <Suspense fallback={<GraphOverlay state={{ kind: "loading" }} />}>
      <GraphCanvas {...canvas} />
    </Suspense>
  );
}
