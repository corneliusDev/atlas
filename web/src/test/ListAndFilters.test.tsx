import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { FiltersPanel } from "../components/FiltersPanel";
import { ListView } from "../components/ListView";
import { DEFAULT_FILTERS, type Filters } from "../lib/filters";
import { ALL_FILTERS, globalGraph } from "../mocks/db";
import { idOf } from "./helpers";

describe("ListView", () => {
  const view = globalGraph(ALL_FILTERS);

  it("lists every node in an accessible table and selects on click", async () => {
    const onSelect = vi.fn();
    render(<ListView view={view} selectedKey={null} highlightKeys={new Set()} onSelect={onSelect} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(view.nodes.length + 1);
    await userEvent.click(within(table).getAllByRole("button", { name: "Sourdough Starter Care" })[0]!);
    expect(onSelect).toHaveBeenCalledWith(`doc:${idOf("Sourdough Starter Care")}`, "Sourdough Starter Care");
  });

  it("puts search matches first", () => {
    const key = `doc:${idOf("Knife Skills")}`;
    render(<ListView view={view} selectedKey={null} highlightKeys={new Set([key])} onSelect={() => {}} />);
    const firstRow = screen.getAllByRole("row")[1]!;
    expect(within(firstRow).getByRole("rowheader")).toHaveTextContent("Knife Skills");
    expect(within(firstRow).getByText("match")).toBeInTheDocument();
  });
});

describe("FiltersPanel", () => {
  function Harness({ onChange, mode = "global" }: { onChange: (f: Filters) => void; mode?: "global" | "local" }) {
    const [filters, setFilters] = useState(DEFAULT_FILTERS);
    const [depth, setDepth] = useState<1 | 2 | 3>(2);
    const view = globalGraph(ALL_FILTERS);
    return (
      <FiltersPanel
        filters={filters}
        onChange={(f) => {
          setFilters(f);
          onChange(f);
        }}
        clusters={view.clusters}
        tags={["cooking", "pricing"]}
        mode={mode}
        depth={depth}
        onDepthChange={setDepth}
      />
    );
  }

  it("toggles cluster, tag and topic-layer filters", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: /Kitchen & fermentation/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ clusters: [expect.any(String)] }));
    await userEvent.click(screen.getByRole("button", { name: "#pricing" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ tags: ["pricing"] }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Show topics" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ showTopics: false }));
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onChange).toHaveBeenLastCalledWith(DEFAULT_FILTERS);
  });

  it("shows the depth slider only for the local graph", () => {
    const { rerender } = render(<Harness onChange={() => {}} />);
    expect(screen.queryByRole("slider", { name: /Depth/ })).not.toBeInTheDocument();
    rerender(<Harness onChange={() => {}} mode="local" />);
    expect(screen.getByRole("slider", { name: /Depth/ })).toHaveValue("2");
    expect(screen.getByRole("slider", { name: /Minimum similarity/ })).toBeInTheDocument();
  });
});
