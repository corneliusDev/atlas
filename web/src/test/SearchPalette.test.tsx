import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SearchHit } from "../api/types";
import { SearchPalette } from "../components/SearchPalette";

describe("SearchPalette", () => {
  it("searches as you type, highlights terms and reports hits for the graph", async () => {
    const onResults = vi.fn();
    render(<SearchPalette clusters={new Map()} onClose={() => {}} onResults={onResults} onPick={() => {}} debounceMs={0} />);
    const input = screen.getByRole("combobox", { name: "Search notes" });
    expect(input).toHaveFocus();
    await userEvent.type(input, "churn");
    const options = await screen.findAllByRole("option");
    expect(options.length).toBeGreaterThan(0);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByText(/churn/i, { selector: "mark" }).length).toBeGreaterThan(0);
    // Server snippets carry <mark> markup: it must render as elements, never as literal text.
    for (const o of options) expect(o.textContent).not.toMatch(/<\/?mark>|&lt;|&amp;/);
    await waitFor(() => expect(onResults).toHaveBeenLastCalledWith("churn", expect.arrayContaining([expect.objectContaining({ document_id: expect.any(String) })])));
  });

  it("Enter picks the active result and closes", async () => {
    const onPick = vi.fn<(h: SearchHit) => void>();
    const onClose = vi.fn();
    render(<SearchPalette clusters={new Map()} onClose={onClose} onResults={() => {}} onPick={onPick} debounceMs={0} />);
    await userEvent.type(screen.getByRole("combobox"), "sourdough");
    await screen.findAllByRole("option");
    await userEvent.keyboard("{ArrowDown}{ArrowUp}{Enter}");
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0]![0].title).toMatch(/Sourdough/);
    expect(onClose).toHaveBeenCalled();
  });

  it("says when nothing matches", async () => {
    render(<SearchPalette clusters={new Map()} onClose={() => {}} onResults={() => {}} onPick={() => {}} debounceMs={0} />);
    await userEvent.type(screen.getByRole("combobox"), "zzqxv");
    expect(await screen.findByText("No matches")).toBeInTheDocument();
  });
});
