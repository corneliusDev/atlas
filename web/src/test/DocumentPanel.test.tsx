import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { DocumentPanel } from "../components/DocumentPanel";
import { idOf, recordRequests } from "./helpers";

const noop = () => {};

function renderPanel(id: string, overrides: Partial<Parameters<typeof DocumentPanel>[0]> = {}) {
  return render(
    <DocumentPanel
      id={id}
      clusters={new Map()}
      onOpen={noop}
      onWhy={noop}
      onFeedback={async (a, b, v) => {
        await api.linkFeedback(a, b, v);
      }}
      version={0}
      {...overrides}
    />,
  );
}

describe("DocumentPanel", () => {
  it("renders title, summary, tags, frontmatter, markdown and backlinks", async () => {
    renderPanel(idOf("Sourdough Starter Care"));
    expect(await screen.findByRole("heading", { level: 2, name: "Sourdough Starter Care" })).toBeInTheDocument();
    expect(screen.getByText(/Feed 1:5:5 when warm/, { selector: ".summary" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Tags" })).getByText("#fermentation")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Frontmatter" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Backlinks/ })).toBeInTheDocument();
    // Sourdough Bread links here with [[Sourdough Starter Care]].
    expect(screen.getAllByRole("button", { name: "Sourdough Bread" }).length).toBeGreaterThan(0);
  });

  it("lists related documents with reasons and opens the evidence dialog", async () => {
    const onWhy = vi.fn();
    renderPanel(idOf("Sourdough Starter Care"), { onWhy });
    const reason = await screen.findByText("Both explain how salt and temperature steer microbial fermentation.");
    const item = reason.closest("li")!;
    expect(within(item).getByRole("button", { name: "Fermentation Log" })).toBeInTheDocument();
    await userEvent.click(within(item).getByRole("button", { name: "Why connected?" }));
    expect(onWhy).toHaveBeenCalledWith(idOf("Sourdough Starter Care"), idOf("Fermentation Log"));
  });

  it("confirm and hide call PUT /api/links/{a}/{b}/feedback", async () => {
    const requests = recordRequests();
    renderPanel(idOf("Sourdough Starter Care"));
    const item = (await screen.findByText(/salt and temperature steer/)).closest("li")!;

    await userEvent.click(within(item).getByRole("button", { name: /Confirm link between/ }));
    await waitFor(() => expect(within(item).getByRole("button", { name: /Confirm link/ })).toHaveAttribute("aria-pressed", "true"));
    const put = requests.find((r) => r.method === "PUT")!;
    expect(put.url.pathname).toBe(`/api/links/${idOf("Sourdough Starter Care")}/${idOf("Fermentation Log")}/feedback`);
    expect(await put.body()).toEqual({ verdict: "confirmed" });

    await userEvent.click(within(item).getByRole("button", { name: /Hide link between/ }));
    await waitFor(() => expect(screen.queryByText(/salt and temperature steer/)).not.toBeInTheDocument());
    expect(screen.getByText(/Hid the link to Fermentation Log/)).toBeInTheDocument();
  });
});
