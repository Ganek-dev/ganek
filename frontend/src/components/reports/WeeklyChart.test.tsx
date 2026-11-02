import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { reportsFixture } from "./reportsFixture";
import { WeeklyChart } from "./WeeklyChart";

const weeks = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    week_start: new Date(Date.UTC(2025, 0, 6 + i * 7)).toISOString().slice(0, 10),
    count: i + 1,
  }));

describe("WeeklyChart", () => {
  it("labels the chart and draws one bar per week in one colour", () => {
    render(<WeeklyChart weekly={reportsFixture.weekly} period="90d" />);
    expect(
      screen.getByRole("img", { name: "Applications per week, 3 weeks, 34 applications" }),
    ).toBeInTheDocument();
    const bars = screen.getAllByTestId("weekly-bar");
    expect(bars).toHaveLength(3);
    expect(new Set(bars.map((b) => (b as HTMLElement).style.background)).size).toBe(1);
  });

  it("keeps the last 53 weeks for period all", () => {
    render(<WeeklyChart weekly={weeks(80)} period="all" />);
    expect(screen.getAllByTestId("weekly-bar")).toHaveLength(53);
    expect(screen.getByText("last 53 weeks")).toBeInTheDocument();
  });

  it("shows every week for a bounded period", () => {
    render(<WeeklyChart weekly={weeks(30)} period="12m" />);
    expect(screen.getAllByTestId("weekly-bar")).toHaveLength(30);
  });

  it("has a table under the chart", () => {
    render(<WeeklyChart weekly={reportsFixture.weekly} period="90d" />);
    expect(screen.getByRole("row", { name: "2026-10-12 14" })).toBeInTheDocument();
  });
});
