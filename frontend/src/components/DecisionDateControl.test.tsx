import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DecisionDateControl } from "./DecisionDateControl";

const APPLIED = "2026-10-28T09:30:00Z";

describe("DecisionDateControl", () => {
  it("says the settings default applies when no date is set", () => {
    render(<DecisionDateControl value={null} appliedAt={APPLIED} onSave={vi.fn()} />);
    expect(screen.getByText(/the Hiring settings default/)).toBeInTheDocument();
  });

  it("shows the team's own date as that calendar day", () => {
    render(<DecisionDateControl value="2026-11-30" appliedAt={APPLIED} onSave={vi.fn()} />);
    expect(screen.getByText(/Nov 30, 2026/)).toBeInTheDocument();
  });

  it("saves a picked date and closes the editor", async () => {
    const onSave = vi.fn().mockResolvedValue(null);
    render(<DecisionDateControl value={null} appliedAt={APPLIED} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    const input = screen.getByLabelText("Decision expected by");
    expect(input).toHaveAttribute("min", "2026-10-28");
    await userEvent.type(input, "2026-11-20");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith("2026-11-20");
    expect(screen.queryByLabelText("Decision expected by")).toBeNull();
  });

  it("refuses a date before the application without a request", async () => {
    const onSave = vi.fn();
    render(<DecisionDateControl value={null} appliedAt={APPLIED} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    const input = screen.getByLabelText("Decision expected by");
    await userEvent.type(input, "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    // the native min check stops the submit before any request
    expect(input).toBeInvalid();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("goes back to the settings default with null", async () => {
    const onSave = vi.fn().mockResolvedValue(null);
    render(<DecisionDateControl value="2026-11-30" appliedAt={APPLIED} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    await userEvent.click(screen.getByRole("button", { name: "Use the settings default" }));
    expect(onSave).toHaveBeenCalledWith(null);
  });

  it("keeps the editor open and shows the server's error", async () => {
    const onSave = vi.fn().mockResolvedValue("The decision date must be within a year");
    render(<DecisionDateControl value={null} appliedAt={APPLIED} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    await userEvent.type(screen.getByLabelText("Decision expected by"), "2026-11-20");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/within a year/);
    expect(screen.getByLabelText("Decision expected by")).toBeInTheDocument();
  });
});
