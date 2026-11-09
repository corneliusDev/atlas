import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { Blob as NodeBlob, File as NodeFile } from "node:buffer";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "../mocks/node";
import { resetMockDb } from "../mocks/db";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockDb();
  try {
    window.localStorage.clear();
  } catch {
    /* storage unavailable */
  }
});
afterAll(() => server.close());

// jsdom gaps used by the UI.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};

// jsdom's File/Blob cannot be streamed by Node's fetch (undici), so multipart uploads hang.
// Use Node's own implementations; they satisfy every File API the UI and MSW touch.
globalThis.Blob = NodeBlob as unknown as typeof Blob;
globalThis.File = NodeFile as unknown as typeof File;
// jsdom also swaps in its own FormData; recover Node's (undici) constructor from a Response.
const nodeFormData = (await new Response("x=1", { headers: { "content-type": "application/x-www-form-urlencoded" } }).formData()).constructor;
globalThis.FormData = nodeFormData as typeof FormData;
