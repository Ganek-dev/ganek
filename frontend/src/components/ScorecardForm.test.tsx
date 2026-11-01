import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ScorecardForm } from "./ScorecardForm";

const criteria = [
  { id: "c1", label: "Communication", hint: "Clear and concise" },
  { id: "c2", label: "Problem solving", hint: "" },
];

describe("ScorecardForm", () => {
  it("submits ratings, recommendation and a trimmed comment; not assessed is omitted", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ScorecardForm criteria={criteria} onSubmit={onSubmit} submitLabel="Submit scorecard" />);

    const first = screen.getByRole("radiogroup", { name: "Communication" });
    await userEvent.click(within(first).getByLabelText("3 of 4"));
    expect(within(screen.getByRole("radiogroup", { name: "Problem solving" })).getByLabelText("Not assessed")).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Strong yes" }));
    await userEvent.type(screen.getByLabelText("Comment"), "  Great  ");
    await userEvent.click(screen.getByRole("button", { name: "Submit scorecard" }));

    expect(onSubmit).toHaveBeenCalledWith({
      ratings: { c1: 3 },
      recommendation: "strong_yes",
      comment: "Great",
    });
  });

  it("sends a null comment when blank and lets a rating go back to not assessed", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ScorecardForm criteria={criteria} onSubmit={onSubmit} submitLabel="Go" />);
    const group = screen.getByRole("radiogroup", { name: "Communication" });
    await userEvent.click(within(group).getByLabelText("2 of 4"));
    await userEvent.click(within(group).getByLabelText("Not assessed"));
    await userEvent.click(screen.getByRole("button", { name: "No" }));
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onSubmit).toHaveBeenCalledWith({ ratings: {}, recommendation: "no", comment: null });
  });

  it("disables submit until a recommendation is picked", async () => {
    render(<ScorecardForm criteria={criteria} onSubmit={vi.fn()} submitLabel="Submit scorecard" />);
    const submit = screen.getByRole("button", { name: "Submit scorecard" });
    expect(submit).toBeDisabled();
    const yes = screen.getByRole("button", { name: "Yes" });
    expect(yes).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(yes);
    expect(yes).toHaveAttribute("aria-pressed", "true");
    expect(submit).toBeEnabled();
  });

  it("prefills from initial", () => {
    render(
      <ScorecardForm
        criteria={criteria}
        initial={{ ratings: { c2: 4 }, recommendation: "yes", comment: "Solid" }}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );
    expect(
      within(screen.getByRole("radiogroup", { name: "Problem solving" })).getByLabelText("4 of 4"),
    ).toBeChecked();
    expect(screen.getByRole("button", { name: "Yes" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Comment")).toHaveValue("Solid");
  });

  it("keeps the typed input and shows the error when submit fails", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("Edit window closed"));
    render(<ScorecardForm criteria={criteria} onSubmit={onSubmit} submitLabel="Save" />);
    await userEvent.click(screen.getByRole("button", { name: "Yes" }));
    await userEvent.type(screen.getByLabelText("Comment"), "keep me");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Edit window closed");
    expect(screen.getByLabelText("Comment")).toHaveValue("keep me");
    expect(screen.getByRole("button", { name: "Yes" })).toHaveAttribute("aria-pressed", "true");
  });

  it("offers the decline link only with a handler and calls it", async () => {
    const onDecline = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <ScorecardForm criteria={criteria} onSubmit={vi.fn()} submitLabel="Save" />,
    );
    expect(screen.queryByText("I did not assess this candidate")).not.toBeInTheDocument();
    rerender(
      <ScorecardForm criteria={criteria} onSubmit={vi.fn()} onDecline={onDecline} submitLabel="Save" />,
    );
    await userEvent.click(screen.getByText("I did not assess this candidate"));
    expect(onDecline).toHaveBeenCalled();
  });
});
