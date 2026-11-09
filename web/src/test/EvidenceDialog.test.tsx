import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EvidenceDialog } from "../components/EvidenceDialog";
import { idOf } from "./helpers";

describe("EvidenceDialog", () => {
  it("shows the score, reason and both passages side by side", async () => {
    render(<EvidenceDialog a={idOf("Fermentation Log")} b={idOf("Sourdough Starter Care")} onClose={() => {}} onFeedback={async () => {}} onOpen={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Why connected?" })).toBeInTheDocument();
    expect(await screen.findByText("84% similar")).toBeInTheDocument();
    expect(screen.getByText(/salt and temperature steer/)).toBeInTheDocument();
    expect(screen.getAllByRole("figure")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Fermentation Log" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sourdough Starter Care" })).toBeInTheDocument();
  });

  it("hiding the link sends feedback and closes", async () => {
    const onFeedback = vi.fn(async () => {});
    const onClose = vi.fn();
    render(<EvidenceDialog a={idOf("Fermentation Log")} b={idOf("Sourdough Starter Care")} onClose={onClose} onFeedback={onFeedback} onOpen={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: /Hide link between/ }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onFeedback).toHaveBeenCalledWith(expect.any(String), expect.any(String), "hidden");
  });

  it("explains when the documents are not linked", async () => {
    render(<EvidenceDialog a={idOf("Knife Skills")} b={idOf("Tokyo Itinerary")} onClose={() => {}} onFeedback={async () => {}} onOpen={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer linked");
  });

  it("Escape closes the dialog", async () => {
    const onClose = vi.fn();
    render(<EvidenceDialog a={idOf("Fermentation Log")} b={idOf("Sourdough Starter Care")} onClose={onClose} onFeedback={async () => {}} onOpen={() => {}} />);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
