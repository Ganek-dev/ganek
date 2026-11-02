import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Funnel } from "./Funnel";
import { reportsFixture } from "./reportsFixture";

function setup() {
  return render(<Funnel steps={reportsFixture.funnel} quiz={reportsFixture.quiz} />);
}

describe("Funnel", () => {
  it("labels the chart with every step and its pass-through", () => {
    setup();
    expect(
      screen.getByRole("img", {
        name: "Funnel: Applied 142, 62 percent move on; Screening 88, 35 percent move on; Interview 31, 19 percent move on; Offer 6, 50 percent move on; Hired 3",
      }),
    ).toBeInTheDocument();
  });

  it("names the first step Applied and prints pass-through between rows", () => {
    setup();
    const chart = screen.getByTestId("funnel-wide");
    expect(within(chart).getByText("Applied")).toBeInTheDocument();
    expect(within(chart).getByText("62 percent")).toBeInTheDocument();
    expect(within(chart).getByText("35 percent")).toBeInTheDocument();
    expect(within(chart).getByText("19 percent")).toBeInTheDocument();
    expect(within(chart).getByText("50 percent")).toBeInTheDocument();
    // nothing after the last row
    expect(within(chart).getAllByText(/ percent$/)).toHaveLength(4);
  });

  it("scales bars to the first step with the shared unit", () => {
    setup();
    const bars = screen.getAllByTestId("funnel-bar");
    expect(bars[0].getAttribute("style")).toContain("calc(var(--funnel-w) * 1)");
    expect(bars[2].getAttribute("style")).toContain(String(31 / 142));
    const splits = screen.getAllByTestId("split-segment");
    // same unit as the bar: 38 of 142 for the first rejected segment
    expect(splits[0].getAttribute("style")).toContain(String(38 / 142));
  });

  it("prints the split counts beside every bar", () => {
    setup();
    const chart = screen.getByTestId("funnel-wide");
    const row = within(chart).getByText("Screening").closest("[data-row]") as HTMLElement;
    expect(within(row).getByText("42")).toBeInTheDocument();
    expect(within(row).getByText("5")).toBeInTheDocument();
    expect(within(row).getAllByText("10")).toHaveLength(1);
  });

  it("shows dashes in the split cells of the last step", () => {
    setup();
    const row = within(screen.getByTestId("funnel-wide")).getByText("Hired").closest("[data-row]") as HTMLElement;
    expect(within(row).getAllByText("-")).toHaveLength(3);
  });

  it("renders the quiz line", () => {
    setup();
    expect(
      screen.getByText("Quiz: 120 invited, 97 completed (81 percent), 14 expired"),
    ).toBeInTheDocument();
  });

  it("offers the numbers as a table", () => {
    setup();
    const summary = screen.getByText("View as table");
    expect(summary.tagName).toBe("SUMMARY");
    const table = within(summary.closest("details") as HTMLElement).getByRole("table");
    expect(within(table).getByRole("row", { name: /Screening 88 35 percent 42 5 10/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /Hired 3 - - - -/ })).toBeInTheDocument();
  });

  it("copes with an empty cohort", () => {
    const empty = reportsFixture.funnel.map((s) => ({
      ...s,
      reached: 0,
      pass_through: null,
      rejected_from: 0,
      withdrawn_from: 0,
      still_here: 0,
    }));
    render(<Funnel steps={empty} quiz={{ invited: 0, completed: 0, expired: 0 }} />);
    expect(screen.getByText("Quiz: 0 invited, 0 completed (-), 0 expired")).toBeInTheDocument();
  });

  it("stacks each step with a counts line for small screens", () => {
    setup();
    const stacked = screen.getByTestId("funnel-stacked");
    expect(within(stacked).getByText("42 rejected · 5 withdrawn · 10 still here")).toBeInTheDocument();
    expect(within(stacked).getAllByTestId("split-counts")).toHaveLength(4);
    expect(within(stacked).getByText("35 percent")).toBeInTheDocument();
    expect(within(stacked).getAllByTestId("funnel-bar-stacked")).toHaveLength(5);
  });
});
