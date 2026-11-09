import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

async function boot() {
  // VITE_USE_MOCKS=1 serves the whole API from MSW (src/mocks), so the UI runs with no backend.
  if (import.meta.env.VITE_USE_MOCKS === "1") {
    const { startMockWorker } = await import("./mocks/browser");
    await startMockWorker();
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void boot();
