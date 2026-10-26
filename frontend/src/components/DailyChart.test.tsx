import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DailyChart } from "./DailyChart";

function series(overrides: Record<number, { views: number; applications: number }> = {}) {
  return Array.from({ length: 30 }, (_, i) => ({
    day: `2026-10-${String(i + 1).padStart(2, "0")}`,
    views: overrides[i]?.views ?? 0,
    applications: overrides[i]?.applications ?? 0,
  }));
}

describe("DailyChart", () => {
  it("draws one column per day with a readable title", () => {
    render(<DailyChart daily={series({ 2: { views: 12, applications: 1 }, 29: { views: 3, applications: 2 } })} />);
    expect(screen.getByRole("img", { name: "Views and applications, last 30 days" })).toBeInTheDocument();
    expect(screen.getAllByTitle(/view/)).toHaveLength(30);
    expect(screen.getByTitle("Oct 3: 12 views, 1 application")).toBeInTheDocument();
    expect(screen.getByTitle("Oct 30: 3 views, 2 applications")).toBeInTheDocument();
    expect(screen.getByTitle("Oct 1: 0 views, 0 applications")).toBeInTheDocument();
  });

  it("invites sharing when nothing was viewed yet", () => {
    const { container } = render(<DailyChart daily={series()} />);
    expect(screen.getByText(/No views yet\. Share the public link to start counting\./)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/visitor/i);
    expect(container.textContent).not.toMatch(/[–—]/);
  });

  it("drops the empty-state line once a view exists", () => {
    render(<DailyChart daily={series({ 5: { views: 1, applications: 0 } })} />);
    expect(screen.queryByText(/No views yet/)).not.toBeInTheDocument();
  });

  it("labels the legend with views and applications", () => {
    render(<DailyChart daily={series()} />);
    expect(screen.getByText("views")).toBeInTheDocument();
    expect(screen.getByText("applications")).toBeInTheDocument();
  });
});
