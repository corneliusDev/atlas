import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { UploadResponse } from "../api/types";
import { ProgressTray } from "../components/ProgressTray";
import { UploadZone } from "../components/UploadZone";
import { resetMockDb } from "../mocks/db";

const md = (name: string, text = "# Title\n\nBody") => new File([text], name, { type: "text/markdown" });

describe("UploadZone", () => {
  it("shows the first-run prompt and POSTs picked files to /api/uploads", async () => {
    const onUploaded = vi.fn<(r: UploadResponse) => void>();
    render(<UploadZone variant="hero" onUploaded={onUploaded} />);
    expect(screen.getByRole("heading", { name: "Drop your .md files here" })).toBeInTheDocument();
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(screen.getByTestId("upload-input"), [md("note.md"), new File(["x"], "photo.png", { type: "image/png" })]);
    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    const res = onUploaded.mock.calls[0]![0];
    expect(res.accepted.map((a) => a.path)).toEqual(["uploads/note.md"]);
    expect(res.ignored).toEqual([{ path: "photo.png", reason: "not_markdown" }]);
  });

  it("accepts files dropped on the zone", async () => {
    const onUploaded = vi.fn();
    render(<UploadZone variant="hero" onUploaded={onUploaded} />);
    const zone = screen.getByRole("heading", { name: /Drop your/ }).closest(".dropzone")!;
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.drop(zone, { dataTransfer: { files: [md("dropped.md")] } });
    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
  });
});

describe("ProgressTray", () => {
  it("shows per-file status, failure reasons, ignored files and the done summary", async () => {
    resetMockDb({ empty: true });
    await api.upload([md("good.md"), md("will-fail.md")]);
    await api.jobsStatus(); // queued -> indexing
    const status = await api.jobsStatus(); // indexing -> linked | failed
    const onZoom = vi.fn();
    render(
      <ProgressTray
        status={status}
        ignored={[{ path: "big.md", reason: "too_large" }]}
        summary={{ stats: { documents: 40, clusters: 6, links: 112, topics: 9 }, topClusters: [{ id: "c1", label: "Pricing", color: "#f00", size: 9 }] }}
        onDismiss={() => {}}
        onOpenDocument={() => {}}
        onZoomCluster={onZoom}
      />,
    );
    const tray = screen.getByRole("region", { name: "Upload progress" });
    expect(within(tray).getByText("Done, 1 failed")).toBeInTheDocument();
    expect(within(tray).getByText("Linked")).toBeInTheDocument();
    expect(within(tray).getByText("Failed")).toBeInTheDocument();
    expect(within(tray).getByText(/Model unavailable/)).toBeInTheDocument();
    expect(within(tray).getByText("1 ignored file")).toBeInTheDocument();
    expect(within(tray).getByText(/larger than 5 MB/)).toBeInTheDocument();
    expect(tray).toHaveTextContent("40 documents, 6 themes, 112 connections");
    await userEvent.click(within(tray).getByRole("button", { name: "Pricing" }));
    expect(onZoom).toHaveBeenCalledWith("c1");
  });

  it("reports progress while files are in flight", async () => {
    resetMockDb({ empty: true });
    await api.upload([md("a.md"), md("b.md")]);
    const status = await api.jobsStatus();
    render(<ProgressTray status={status} ignored={[]} summary={null} onDismiss={() => {}} onOpenDocument={() => {}} onZoomCluster={() => {}} />);
    expect(screen.getByText("Indexing 0 of 2 files")).toBeInTheDocument();
    expect(screen.getAllByRole("list", { name: "Step 3 of 6: Embedding passages" })).toHaveLength(2);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(screen.queryByRole("button", { name: "Dismiss progress" })).not.toBeInTheDocument();
  });
});
