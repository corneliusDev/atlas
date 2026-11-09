import { act, createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import App from "../App";
import type { FileProgress, JobsStatusResponse, UploadResponse } from "../api/types";
import { DropOverlay, dropOverlayText, useWindowFileDrag } from "../components/DropOverlay";
import { GraphOverlay, arrangingText } from "../components/graph/GraphOverlay";
import { ProgressTray } from "../components/ProgressTray";
import { StageStepper } from "../components/StageStepper";
import { UploadCard } from "../components/UploadCard";
import { UploadZone, useUpload, type UploadController, type UploadState } from "../components/UploadZone";
import {
  WORKER_CONCURRENCY,
  formatElapsed,
  formatEta,
  groupTrayFiles,
  isFreshLayout,
  layoutBudgetMs,
  layoutProgress,
  rawEtaSeconds,
  smoothEta,
  uploadSummary,
} from "../lib/progress";
import { server } from "../mocks/node";
import { recordRequests } from "./helpers";

const md = (name: string, text = "# Title\n\nBody") => new File([text], name, { type: "text/markdown" });

let seq = 0;
function file(status: FileProgress["status"], patch: Partial<FileProgress> = {}): FileProgress {
  seq += 1;
  return {
    job_id: `job-${seq}`,
    path: `uploads/note-${seq}.md`,
    kind: "upsert",
    status,
    stage: status === "indexing" ? "embedding" : null,
    started_at: status === "indexing" ? new Date().toISOString() : null,
    attempts: status === "queued" ? 0 : 1,
    error: status === "failed" ? { kind: "model_timeout", step: "summarize" } : null,
    outcome: status === "linked" ? { kind: "indexed", document_id: `d-${seq}`, path: `uploads/note-${seq}.md`, link_count: 4, topic_count: 1, cluster_id: null } : null,
    updated_at: new Date(Date.UTC(2026, 10, 1, 9, 0, seq)).toISOString(),
    ...patch,
  };
}

function statusOf(files: FileProgress[], avg: number | null): JobsStatusResponse {
  const counts = { pending: 0, running: 0, done: 0, failed: 0 };
  for (const f of files) counts[({ queued: "pending", indexing: "running", linked: "done", failed: "failed" } as const)[f.status]] += 1;
  return { vault: "v", counts, files, recent_failures: [], recluster_pending: false, idle: counts.pending + counts.running === 0, avg_seconds_per_file: avg };
}

// ---------------------------------------------------------------------------------------------

describe("ETA", () => {
  it("formats coarse, calm wording", () => {
    expect(formatEta(null)).toBeNull();
    expect(formatEta(0)).toBeNull();
    expect(formatEta(-12)).toBeNull();
    expect(formatEta(Number.NaN)).toBeNull();
    expect(formatEta(4)).toBe("a few seconds");
    expect(formatEta(9)).toBe("a few seconds");
    expect(formatEta(12)).toBe("about 10 sec");
    expect(formatEta(19)).toBe("about 20 sec");
    expect(formatEta(34)).toBe("about 30 sec");
    expect(formatEta(56)).toBe("about 1 min");
    expect(formatEta(75)).toBe("about 1 min");
    expect(formatEta(150)).toBe("about 3 min");
    expect(formatEta(7200)).toBe("about 2 hr");
  });

  it("derives raw seconds from avg_seconds_per_file, files left and the worker pool", () => {
    expect(WORKER_CONCURRENCY).toBe(2);
    expect(rawEtaSeconds({ counts: { pending: 10, running: 2, done: 3 }, avg_seconds_per_file: 6 })).toBe(36);
    expect(rawEtaSeconds({ counts: { pending: 0, running: 1 }, avg_seconds_per_file: 6 })).toBe(6);
    expect(rawEtaSeconds({ counts: { pending: 5 }, avg_seconds_per_file: null })).toBeNull();
    expect(rawEtaSeconds({ counts: { done: 5 }, avg_seconds_per_file: 4 })).toBeNull();
    expect(rawEtaSeconds(null)).toBeNull();
    // Running files only count for the time they have left.
    const now = Date.parse("2026-11-08T10:00:00Z");
    const running = [file("indexing", { started_at: "2026-11-08T09:59:56Z" }), file("indexing", { started_at: "2026-11-08T09:59:58Z" })];
    expect(rawEtaSeconds({ counts: { pending: 4, running: 2 }, avg_seconds_per_file: 6, files: running }, now)).toBe((6 * 4 + 2 + 4) / 2);
  });

  it("smooths: counts down between polls, damps jitter, never goes negative", () => {
    let s = smoothEta(null, 60, 0);
    expect(s).toEqual({ value: 60, at: 0 });
    s = smoothEta(s, 60, 10_000);
    expect(s!.value).toBeCloseTo(52.5);
    // Jittery raw values move the estimate only a little.
    const a = smoothEta({ value: 100, at: 0 }, 140, 0)!;
    const b = smoothEta({ value: 100, at: 0 }, 70, 0)!;
    expect(a.value).toBeLessThan(115);
    expect(b.value).toBeGreaterThan(90);
    // Long gap: clamps at zero.
    expect(smoothEta({ value: 5, at: 0 }, 0, 60_000)!.value).toBe(0);
    // A new, much larger batch resets the estimate.
    expect(smoothEta({ value: 10, at: 0 }, 600, 1000)!.value).toBe(600);
    expect(smoothEta({ value: 10, at: 0 }, null, 1000)).toBeNull();
  });

  it("formats elapsed time and ignores clock skew", () => {
    const now = Date.parse("2026-11-08T10:00:00Z");
    expect(formatElapsed("2026-11-08T09:59:48Z", now)).toBe("12s");
    expect(formatElapsed("2026-11-08T09:58:55Z", now)).toBe("1m 05s");
    expect(formatElapsed("2026-11-08T10:00:03Z", now)).toBe("0s");
    expect(formatElapsed(null, now)).toBeNull();
  });
});

describe("StageStepper", () => {
  it("marks earlier steps done and the current step active", () => {
    render(<StageStepper stage="enriching" />);
    const list = screen.getByRole("list", { name: "Step 4 of 6: Summarize with Claude" });
    const steps = within(list).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent)).toEqual(["Read", "Parse", "Embed", "Summarize", "Link", "Save"]);
    expect(steps.map((s) => s.className.replace("step is-", ""))).toEqual(["done", "done", "done", "active", "todo", "todo"]);
    expect(steps[3]).toHaveAttribute("aria-current", "step");
  });

  it("shows every step pending before the backend reports a stage", () => {
    render(<StageStepper stage={null} />);
    const list = screen.getByRole("list", { name: "Starting" });
    expect(within(list).getAllByRole("listitem").every((s) => s.classList.contains("is-todo"))).toBe(true);
  });
});

describe("ProgressTray with stages", () => {
  it("orders 50 files: in flight first, then failed and recent done, the rest collapsed", () => {
    const files = [
      ...Array.from({ length: 20 }, () => file("linked")),
      file("failed"),
      ...Array.from({ length: 27 }, () => file("queued")),
      file("indexing"),
      file("indexing"),
    ].reverse();
    const { visible, hidden } = groupTrayFiles(files);
    expect(visible.map((f) => f.status)).toEqual([
      "indexing",
      "indexing",
      "failed",
      ...Array<string>(5).fill("linked"),
      ...Array<string>(3).fill("queued"),
    ]);
    expect(hidden).toHaveLength(50 - visible.length);
  });

  it("shows the ETA heading, stage rows with elapsed time, link counts and a collapsed remainder", async () => {
    const started = new Date(Date.now() - 12_400).toISOString();
    const files = [
      file("indexing", { path: "uploads/pricing.md", stage: "enriching", started_at: started }),
      file("indexing", { path: "uploads/churn.md", stage: "reading" }),
      ...Array.from({ length: 8 }, () => file("queued")),
      ...Array.from({ length: 40 }, () => file("linked")),
    ];
    render(<ProgressTray status={statusOf(files, 6)} ignored={[]} summary={null} onDismiss={() => {}} onOpenDocument={() => {}} onZoomCluster={() => {}} />);
    // (6 s x 8 queued + what the 2 running files have left) / 2 workers = about 30 s.
    expect(screen.getByText(/Indexing 40 of 50 files/)).toHaveTextContent("Indexing 40 of 50 files · about 30 sec left");
    const row = screen.getByText("pricing.md").closest("li")!;
    expect(within(row).getByText("Summarize with Claude")).toBeInTheDocument();
    expect(within(row).getByText("12s")).toBeInTheDocument();
    expect(within(row).getByRole("list", { name: "Step 4 of 6: Summarize with Claude" })).toBeInTheDocument();
    expect(screen.getAllByText("4 links").length).toBe(5);
    expect(screen.getByRole("status")).toHaveTextContent("Indexing 50 files");
    const more = screen.getByRole("button", { name: "Show 40 more (5 queued, 35 done)" });
    await userEvent.click(more);
    expect(screen.getAllByText("4 links").length).toBe(40);
    expect(screen.getByRole("button", { name: "Show fewer" })).toBeInTheDocument();
  });

  it("omits the ETA while it is unknown", () => {
    render(<ProgressTray status={statusOf([file("indexing"), file("queued")], null)} ignored={[]} summary={null} onDismiss={() => {}} onOpenDocument={() => {}} onZoomCluster={() => {}} />);
    expect(screen.getByText("Indexing 0 of 2 files")).toBeInTheDocument();
    expect(screen.queryByText(/left/)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------------

function fakeController(state: UploadState, patch: Partial<UploadController> = {}): UploadController {
  return { state, busy: state.phase === "sending" || state.phase === "processing", send: vi.fn(), retry: vi.fn(), dismiss: vi.fn(), ...patch };
}

const RESULT: UploadResponse = {
  vault: "v",
  accepted: [
    { path: "uploads/a.md", job_id: "1", unchanged: false },
    { path: "uploads/b.md", job_id: "2", unchanged: false },
    { path: "uploads/c.md", job_id: "3", unchanged: false },
  ],
  ignored: [{ path: "photo.png", reason: "not_markdown" }],
};

describe("UploadCard", () => {
  it("shows file count, size and byte progress while sending", () => {
    render(<UploadCard upload={fakeController({ phase: "sending", files: 3, bytes: 12_288, loaded: 5160, total: 12_288 })} />);
    const card = screen.getByRole("region", { name: "Upload status" });
    expect(card).toHaveTextContent("Uploading 3 files · 12 KB");
    expect(card).toHaveTextContent("41%");
    expect(within(card).getByRole("progressbar", { name: "Upload progress" })).toHaveAttribute("aria-valuenow", "41");
  });

  it("says the server is processing once every byte is out", () => {
    render(<UploadCard upload={fakeController({ phase: "processing", files: 3, bytes: 12_288 })} />);
    expect(screen.getByText("Processing on server…")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Processing on server");
  });

  it("reports the result with ignored files and their reasons", async () => {
    const dismiss = vi.fn();
    render(<UploadCard upload={fakeController({ phase: "success", files: 4, bytes: 2000, result: RESULT }, { dismiss })} />);
    const card = screen.getByRole("region", { name: "Upload status" });
    expect(card).toHaveTextContent("3 files uploaded · queued for indexing · 1 ignored");
    expect(card).toHaveTextContent("photo.png not a Markdown file");
    await userEvent.click(within(card).getByRole("button", { name: "Dismiss upload status" }));
    expect(dismiss).toHaveBeenCalled();
  });

  it("offers Retry after an error", async () => {
    const retry = vi.fn();
    render(<UploadCard upload={fakeController({ phase: "error", files: 2, bytes: 100, message: "API 500: disk full" }, { retry })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Upload failed");
    expect(screen.getByRole("alert")).toHaveTextContent("disk full");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();
  });

  it("summarises edge cases", () => {
    expect(uploadSummary({ vault: "v", accepted: [], ignored: [{ path: "x.png", reason: "not_markdown" }] })).toEqual({ headline: "No files uploaded", ignored: "1 ignored" });
    expect(uploadSummary({ vault: "v", accepted: [{ path: "a", job_id: "1", unchanged: true }], ignored: [] }).headline).toBe("1 file uploaded · already up to date");
  });
});

function Harness() {
  const upload = useUpload(() => {});
  const drag = useWindowFileDrag((files) => void upload.send(files));
  return (
    <>
      <UploadZone variant="button" upload={upload} />
      <UploadCard upload={upload} />
      <DropOverlay drag={drag} busy={upload.busy} />
    </>
  );
}

describe("upload flow", () => {
  it("goes from sending to success and ignores a second submit while busy", async () => {
    const seen = recordRequests();
    render(<Harness />);
    const input = screen.getByTestId("upload-input");
    fireEvent.change(input, { target: { files: [md("one.md"), md("two.md"), md("three.md")] } });
    // A second pick while the first upload runs is ignored, and the button is disabled.
    fireEvent.change(input, { target: { files: [md("again.md")] } });
    expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled();
    expect(await screen.findByText("3 files uploaded · queued for indexing", { selector: ".upload-card-title" })).toBeInTheDocument();
    expect(seen.filter((r) => r.method === "POST" && r.url.pathname === "/api/uploads")).toHaveLength(1);
  });

  it("shows an error with Retry, and Retry re-sends the same files", async () => {
    server.use(http.post("*/api/uploads", () => HttpResponse.json({ detail: "disk full" }, { status: 507 }), { once: true }));
    render(<Harness />);
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(screen.getByTestId("upload-input"), [md("one.md"), md("two.md")]);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Upload failed");
    expect(alert).toHaveTextContent("disk full");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("2 files uploaded · queued for indexing", { selector: ".upload-card-title" })).toBeInTheDocument();
  });

  it("shows a full-window overlay while files are dragged over the app and uploads the drop", async () => {
    render(<Harness />);
    const dataTransfer = { types: ["Files"], items: [{ kind: "file" }, { kind: "file" }], files: [md("x.md"), md("y.md")], dropEffect: "none" };
    act(() => {
      fireEvent(window, createEvent.dragEnter(window, { dataTransfer }));
    });
    expect(screen.getByTestId("drop-overlay")).toHaveTextContent("Drop to upload 2 Markdown files");
    act(() => {
      fireEvent(window, createEvent.dragLeave(window, { dataTransfer }));
    });
    expect(screen.queryByTestId("drop-overlay")).not.toBeInTheDocument();
    act(() => {
      fireEvent(window, createEvent.dragEnter(window, { dataTransfer }));
      fireEvent(window, createEvent.drop(window, { dataTransfer }));
    });
    expect(screen.queryByTestId("drop-overlay")).not.toBeInTheDocument();
    expect(await screen.findByText("2 files uploaded · queued for indexing", { selector: ".upload-card-title" })).toBeInTheDocument();
  });

  it("words the overlay with or without a file count", () => {
    expect(dropOverlayText(1)).toBe("Drop to upload 1 Markdown file");
    expect(dropOverlayText(null)).toBe("Drop to upload Markdown files");
  });
});

// ---------------------------------------------------------------------------------------------

describe("graph overlays", () => {
  it("shows a spinner while the graph loads", () => {
    render(<GraphOverlay state={{ kind: "loading" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading your notes…");
  });

  it("shows determinate progress while arranging and fades out when settled", () => {
    const { rerender } = render(<GraphOverlay state={{ kind: "arranging", notes: 126, links: 587, progress: 0.4 }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Arranging 126 notes and 587 links…");
    expect(screen.getByRole("progressbar", { name: "Layout progress" })).toHaveAttribute("aria-valuenow", "40");
    rerender(<GraphOverlay state={{ kind: "arranging", notes: 126, links: 587, progress: 1, leaving: true }} />);
    expect(screen.getByTestId("graph-overlay")).toHaveClass("is-leaving");
    expect(arrangingText(1, 1)).toBe("Arranging 1 note and 1 link…");
  });

  it("offers Retry on error", async () => {
    const onRetry = vi.fn();
    render(<GraphOverlay state={{ kind: "error", message: "API 500: boom", onRetry }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load the graph");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("budgets and measures the layout, and only announces fresh layouts", () => {
    expect(layoutBudgetMs(10)).toBe(1560);
    expect(layoutBudgetMs(5000)).toBe(6000);
    expect(layoutProgress(-5, 1000)).toBe(0);
    expect(layoutProgress(500, 1000)).toBe(0.5);
    expect(layoutProgress(5000, 1000)).toBe(1);
    expect(isFreshLayout(0, 126, 126)).toBe(true);
    expect(isFreshLayout(120, 3, 123)).toBe(false);
    expect(isFreshLayout(10, 30, 40)).toBe(true);
    expect(isFreshLayout(40, 0, 40)).toBe(false);
    expect(isFreshLayout(0, 1, 1)).toBe(false);
  });

  it("App shows the loading overlay, then an error with Retry that recovers", async () => {
    window.localStorage.setItem("atlas.viewMode", "list");
    // Fail only the main view request (all three layers); the catalog asks for documents only.
    let fail = true;
    server.use(
      http.get("*/api/graph", ({ request }) => {
        if (fail && new URL(request.url).searchParams.getAll("layer").length > 1) return HttpResponse.json({ detail: "database is down" }, { status: 500 });
        return undefined;
      }),
    );
    render(<App />);
    expect(screen.getByText("Loading your notes…")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the graph");
    expect(alert).toHaveTextContent("database is down");
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
  });
});
