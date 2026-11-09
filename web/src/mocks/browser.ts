import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
import { enqueueDemoBatch, resetMockDb, setMockRealtime } from "./db";

/**
 * Starts MSW in the browser. URL switches:
 * - `?empty` starts with an empty vault (first-run demo).
 * - `?batch` (or `?batch=50`) queues a batch of synthetic notes so the indexing tray runs at once.
 */
export async function startMockWorker(): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  if (params.has("empty")) resetMockDb({ empty: true });
  setMockRealtime(true);
  if (params.has("batch")) enqueueDemoBatch(Number(params.get("batch")) || 24);
  simulateUploadBandwidth();
  const worker = setupWorker(...handlers);
  await worker.start({ onUnhandledRequest: "bypass", quiet: true });
}

/**
 * Locally the multipart body reaches the service worker instantly, so the byte progress bar
 * would jump straight to 100%. Pace synthetic `progress` events on `xhr.upload` (at ~1.5 MB/s,
 * at least 1.2 s) before the request is really sent, so the upload card's bar is visible.
 */
function simulateUploadBandwidth(): void {
  const urls = new WeakMap<XMLHttpRequest, string>();
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (this: XMLHttpRequest, method: string, url: string | URL, ...rest: unknown[]) {
    urls.set(this, `${method.toUpperCase()} ${String(url)}`);
    return (open as (...a: unknown[]) => void).call(this, method, url, ...rest);
  } as typeof XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.send = function (this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null) {
    const target = urls.get(this) ?? "";
    if (!(target.startsWith("POST ") && target.includes("/api/uploads") && body instanceof FormData)) {
      send.call(this, body);
      return;
    }
    let total = 0;
    for (const value of body.values()) total += typeof value === "string" ? value.length : value.size;
    total = Math.max(total, 1);
    const durationMs = Math.max(1200, Math.min(6000, (total / 1_500_000) * 1000));
    const started = performance.now();
    const step = () => {
      const loaded = Math.min(total, Math.round(((performance.now() - started) / durationMs) * total));
      this.upload.dispatchEvent(new ProgressEvent("progress", { lengthComputable: true, loaded, total }));
      if (loaded < total) window.setTimeout(step, 80);
      else send.call(this, body);
    };
    step();
  };
}
