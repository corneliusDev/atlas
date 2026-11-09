import { SEED_DOCS, docId } from "../mocks/data";
import { server } from "../mocks/node";

/** Mock document id for a seed note title, e.g. "Sourdough Bread". */
export function idOf(title: string): string {
  const i = SEED_DOCS.findIndex((d) => d.title === title);
  if (i < 0) throw new Error(`no seed doc titled ${title}`);
  return docId(i);
}

/** Records every request MSW sees, for asserting on method + path. */
export function recordRequests(): { method: string; url: URL; body: () => Promise<unknown> }[] {
  const seen: { method: string; url: URL; body: () => Promise<unknown> }[] = [];
  server.events.on("request:start", ({ request }) => {
    const clone = request.clone();
    seen.push({ method: request.method, url: new URL(request.url), body: () => clone.json() });
  });
  return seen;
}
