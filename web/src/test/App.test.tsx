import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "../App";
import { resetMockDb } from "../mocks/db";

// jsdom has no WebGL, so the graph area falls back to a prompt; the list view carries the same data.
function renderInListMode() {
  window.localStorage.setItem("atlas.viewMode", "list");
  return render(<App />);
}

describe("App", () => {
  it("shows the empty state when the vault has no documents, and uploads into the tray", { timeout: 15_000 }, async () => {
    resetMockDb({ empty: true });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Drop your .md files here" })).toBeInTheDocument();
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(screen.getByTestId("upload-input"), [new File(["# First note\n\nHello."], "first.md"), new File(["x"], "skip.txt")]);
    const tray = await screen.findByRole("region", { name: "Upload progress" });
    expect(await within(tray).findByText("1 ignored file")).toBeInTheDocument();
    // The tray polls /api/jobs/status until the file is linked, then the graph replaces the empty state.
    expect(await within(tray).findByText("Linked", {}, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Drop your .md files here" })).not.toBeInTheDocument(), { timeout: 4000 });
    await waitFor(() => expect(tray).toHaveTextContent(/1 document, 1 theme, \d+ connections?/), { timeout: 4000 });
  });

  it("falls back to a list prompt without WebGL", async () => {
    render(<App />);
    expect(await screen.findByText(/WebGL is unavailable/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show as list" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("opens the side panel and records travel breadcrumbs with back and forward", async () => {
    renderInListMode();
    const table = await screen.findByRole("table");
    await userEvent.click(within(table).getAllByRole("button", { name: "Sourdough Bread" })[0]!);
    const panel = await screen.findByRole("complementary", { name: "Selection details" });
    expect(await within(panel).findByRole("heading", { level: 2, name: "Sourdough Bread" })).toBeInTheDocument();

    // Step to a topic from the panel, then to another document.
    await userEvent.click(await within(panel).findByRole("button", { name: /wild yeast/ }));
    expect(await within(panel).findByRole("heading", { level: 2, name: "wild yeast" })).toBeInTheDocument();
    await userEvent.click(await within(panel).findByRole("button", { name: "Sourdough Starter Care" }));
    expect(await within(panel).findByRole("heading", { level: 2, name: "Sourdough Starter Care" })).toBeInTheDocument();

    const trail = screen.getByRole("navigation", { name: "Travel path" });
    expect(within(trail).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Sourdough Bread", "topicwild yeast", "Sourdough Starter Care"]);
    await userEvent.click(within(trail).getByRole("button", { name: "Back" }));
    expect(await within(panel).findByRole("heading", { level: 2, name: "wild yeast" })).toBeInTheDocument();
    await userEvent.click(within(trail).getByRole("button", { name: "Forward" }));
    expect(await within(panel).findByRole("heading", { level: 2, name: "Sourdough Starter Care" })).toBeInTheDocument();
  });

  it("switches to the local graph with a depth slider", async () => {
    renderInListMode();
    const table = await screen.findByRole("table");
    const total = within(table).getAllByRole("row").length;
    expect(screen.getByRole("button", { name: "Local" })).toBeDisabled();
    await userEvent.click(within(table).getAllByRole("button", { name: "Knife Skills" })[0]!);
    await userEvent.click(screen.getByRole("button", { name: "Local" }));
    expect(await screen.findByRole("heading", { name: "Local graph as a list" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: /Depth/ })).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByRole("table")).getAllByRole("row").length).toBeLessThan(total));
  });

  it("Cmd+K search highlights matches and picking one opens it in the local graph", async () => {
    renderInListMode();
    await screen.findByRole("table");
    await userEvent.keyboard("{Meta>}k{/Meta}");
    const input = await screen.findByRole("combobox", { name: "Search notes" });
    await userEvent.type(input, "churn");
    await screen.findAllByRole("option");
    expect(await screen.findByText(/\d+ match(es)? for “churn” highlighted/)).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Local graph as a list" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Selection details" })).toBeInTheDocument();
  });

  it("toggles between light and dark themes", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });
});
