import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ScorecardCriterion } from "@/lib/api";

import { ScorecardTemplateEditor } from "./ScorecardTemplateEditor";

const A: ScorecardCriterion = { id: "aaaaaaaa", label: "Problem solving", hint: "Breaks work down" };
const B: ScorecardCriterion = { id: "bbbbbbbb", label: "Communication", hint: "" };
const HINT = "Rate candidates against the criteria you add here.";

function last(onChange: ReturnType<typeof vi.fn>): ScorecardCriterion[] {
  return onChange.mock.calls.at(-1)![0] as ScorecardCriterion[];
}

describe("ScorecardTemplateEditor", () => {
  it("shows the empty hint when there are no criteria", () => {
    render(<ScorecardTemplateEditor value={[]} onChange={vi.fn()} emptyHint={HINT} />);
    expect(screen.getByText(HINT)).toBeInTheDocument();
  });

  it("add appends a criterion with an empty id", async () => {
    const onChange = vi.fn();
    render(<ScorecardTemplateEditor value={[A]} onChange={onChange} emptyHint={HINT} />);
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    expect(last(onChange)).toEqual([A, { id: "", label: "", hint: "" }]);
  });

  it("remove drops the row and keeps the other ids", async () => {
    const onChange = vi.fn();
    render(<ScorecardTemplateEditor value={[A, B]} onChange={onChange} emptyHint={HINT} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]!);
    expect(last(onChange)).toEqual([B]);
  });

  it("move down swaps and round-trips ids", async () => {
    const onChange = vi.fn();
    render(<ScorecardTemplateEditor value={[A, B]} onChange={onChange} emptyHint={HINT} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Move down" })[0]!);
    expect(last(onChange)).toEqual([B, A]);
  });

  it("disables the first Move up and the last Move down", () => {
    render(<ScorecardTemplateEditor value={[A, B]} onChange={vi.fn()} emptyHint={HINT} />);
    expect(screen.getAllByRole("button", { name: "Move up" })[0]).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "Move down" })[1]).toBeDisabled();
  });

  it("edits label and hint, keeping the id", () => {
    const onChange = vi.fn();
    render(<ScorecardTemplateEditor value={[A]} onChange={onChange} emptyHint={HINT} />);
    fireEvent.change(screen.getByLabelText("Criterion label"), { target: { value: "Design" } });
    expect(last(onChange)).toEqual([{ ...A, label: "Design" }]);
    fireEvent.change(screen.getByLabelText("Criterion hint"), { target: { value: "Tradeoffs" } });
    expect(last(onChange)).toEqual([{ ...A, hint: "Tradeoffs" }]);
  });

  it("disables Add criterion at 20", () => {
    const twenty = Array.from({ length: 20 }, (_, i) => ({ id: `id${i}`, label: `C${i}`, hint: "" }));
    render(<ScorecardTemplateEditor value={twenty} onChange={vi.fn()} emptyHint={HINT} />);
    expect(screen.getByRole("button", { name: "Add criterion" })).toBeDisabled();
  });

  it("rejects a label over 120 characters with an inline error", () => {
    const onChange = vi.fn();
    render(<ScorecardTemplateEditor value={[A]} onChange={onChange} emptyHint={HINT} />);
    fireEvent.change(screen.getByLabelText("Criterion label"), { target: { value: "x".repeat(121) } });
    expect(screen.getByText("Keep labels under 120 characters")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Criterion label"), { target: { value: "ok" } });
    expect(screen.queryByText("Keep labels under 120 characters")).not.toBeInTheDocument();
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
