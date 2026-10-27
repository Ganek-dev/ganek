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
    expect(
      screen.getByRole("img", {
        name: "Views and applications, last 30 days: 15 views and 3 applications, Oct 1 to Oct 30.",
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByTitle(/view/)).toHaveLength(30);
    expect(screen.getByTitle("Oct 3: 12 views, 1 application")).toBeInTheDocument();
    expect(screen.getByTitle("Oct 30: 3 views, 2 applications")).toBeInTheDocument();
    expect(screen.getByTitle("Oct 1: 0 views, 0 applications")).toBeInTheDocument();
  });

  it("renders the empty state the page hands it under the bars", () => {
    render(<DailyChart daily={series()} empty={<p>No views were counted.</p>} />);
    expect(screen.getByText("No views were counted.")).toBeInTheDocument();
    expect(screen.getAllByTitle(/view/)).toHaveLength(30);
  });

  it("claims nothing about views on its own", () => {
    const { container } = render(<DailyChart daily={series()} />);
    expect(container.textContent).not.toMatch(/No views/);
  });

  it("labels the legend with views and applications", () => {
    render(<DailyChart daily={series()} />);
    expect(screen.getByText("views")).toBeInTheDocument();
    expect(screen.getByText("applications")).toBeInTheDocument();
  });

  it("sums the period into the accessible name, singulars included", () => {
    render(<DailyChart daily={series({ 0: { views: 1, applications: 1 } })} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Views and applications, last 30 days: 1 view and 1 application, Oct 1 to Oct 30.",
    );
  });
});
