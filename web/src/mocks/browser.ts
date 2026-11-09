import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
import { resetMockDb } from "./db";

/** Starts MSW in the browser. `?empty` in the URL starts with an empty vault (first-run demo). */
export async function startMockWorker(): Promise<void> {
  if (new URLSearchParams(window.location.search).has("empty")) resetMockDb({ empty: true });
  const worker = setupWorker(...handlers);
  await worker.start({ onUnhandledRequest: "bypass", quiet: true });
}
