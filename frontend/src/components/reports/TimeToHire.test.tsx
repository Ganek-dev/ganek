import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { reportsFixture } from "./reportsFixture";
import { TimeToHire, axisMax } from "./TimeToHire";

const cohort = reportsFixture.cohort;

describe("TimeToHire", () => {
  it("draws one labelled dot per hire on a 0 to 45 day strip (R3 07)", () => {
    render(<TimeToHire cohort={cohort} />);
    const strip = screen.getByRole("img", { name: "Hires after 17, 24 and 31 days" });
    const dots = within(strip).getAllByTestId("hire-dot");
    expect(dots).toHaveLength(3);
    expect(within(strip).getByText("17 d")).toBeInTheDocument();
    expect(within(strip).getByText("31 d")).toBeInTheDocument();
    expect(dots[0].getAttribute("style")).toContain(String((17 / 45) * 100));
    expect(screen.getByTitle("Hired after 24 days")).toBeInTheDocument();
    expect(screen.getByText("45 d")).toBeInTheDocument();
    expect(screen.getByText("Median 24 days (n = 3)")).toBeInTheDocument();
  });

  it("draws no average line", () => {
    render(<TimeToHire cohort={cohort} />);
    expect(screen.queryByText(/average|mean/i)).not.toBeInTheDocument();
  });

  it("shares a dot between hires on the same day and lists them in the table", () => {
    render(<TimeToHire cohort={{ ...cohort, hire_days: [5, 5, 5], hires_n: 3, median_time_to_hire_days: 5 }} />);
    expect(screen.getAllByTestId("hire-dot")).toHaveLength(1);
    expect(screen.getByText("5 d x3")).toBeInTheDocument();
    expect(screen.getByTitle("3 hires after 5 days")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: "5 3" })).toBeInTheDocument();
  });

  it("keeps every dot but drops labels that would collide", () => {
    render(<TimeToHire cohort={{ ...cohort, hire_days: [20, 21, 40], hires_n: 3 }} />);
    expect(screen.getAllByTestId("hire-dot")).toHaveLength(3);
    expect(screen.getByText("20 d")).toBeInTheDocument();
    expect(screen.queryByText("21 d")).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: "21 1" })).toBeInTheDocument();
  });

  it("still draws dots below n = 3 with a dash for the median", () => {
    render(<TimeToHire cohort={reportsFixture.previous!} />);
    expect(screen.getAllByTestId("hire-dot")).toHaveLength(2);
    expect(screen.getByText("Median - (n = 2)")).toBeInTheDocument();
  });

  it("says so when there are no hires", () => {
    render(<TimeToHire cohort={{ ...cohort, hire_days: [], hires_n: 0, median_time_to_hire_days: null }} />);
    expect(screen.getByText("No hires in this period.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByText("View as table")).not.toBeInTheDocument();
  });

  it("uses theme tokens for the marks so both modes read", () => {
    render(<TimeToHire cohort={cohort} />);
    const dot = screen.getByTitle("Hired after 17 days");
    expect(dot.getAttribute("style")).toContain("var(--chart-accent)");
    expect(dot.getAttribute("style")).toContain("var(--surface)");
  });

  it("ends the axis a third past the slowest hire, rounded to 5", () => {
    expect(axisMax([17, 24, 31])).toBe(45);
    expect(axisMax([])).toBe(5);
    expect(axisMax([1])).toBe(5);
    expect(axisMax([100])).toBe(140);
  });
});
