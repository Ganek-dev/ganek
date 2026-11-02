import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { reportsFixture } from "./reportsFixture";
import { TimeInStage } from "./TimeInStage";

describe("TimeInStage", () => {
  it("shows the median with n and the oldest live candidate", () => {
    render(<TimeInStage rows={reportsFixture.time_in_stage} />);
    const chart = screen.getByRole("img", { name: /^Time in stage: New median 3 days, n = 132;/ });
    expect(within(chart).getByText("9 d")).toBeInTheDocument();
    expect(within(chart).getByText("(n = 78)")).toBeInTheDocument();
    expect(within(chart).getByText("oldest live candidate: 18 d")).toBeInTheDocument();
  });

  it("scales bars to the longest median", () => {
    render(<TimeInStage rows={reportsFixture.time_in_stage} />);
    const bars = screen.getAllByTestId("stage-bar");
    expect(bars[1]).toHaveStyle({ width: "100%" });
    expect(bars[0].getAttribute("style")).toContain(String((3 / 9) * 100));
  });

  it("shows a dash and no bar below n = 3", () => {
    const rows = [{ stage: "offer" as const, median_days: null, n: 2, oldest_live_days: null }];
    render(<TimeInStage rows={rows} />);
    const chart = screen.getByRole("img");
    expect(within(chart).getByText("-")).toBeInTheDocument();
    expect(within(chart).getByText("(n = 2)")).toBeInTheDocument();
    expect(screen.queryByTestId("stage-bar")).not.toBeInTheDocument();
    expect(screen.queryByText(/oldest live/)).not.toBeInTheDocument();
    expect(within(chart).getByText("no live candidate")).toBeInTheDocument();
  });

  it("has a table under the chart", () => {
    render(<TimeInStage rows={reportsFixture.time_in_stage} />);
    expect(screen.getByRole("row", { name: "Screening 9 78 18" })).toBeInTheDocument();
  });
});
