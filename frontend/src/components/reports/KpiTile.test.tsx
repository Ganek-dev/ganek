import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeltaText, KpiTile } from "./KpiTile";

describe("DeltaText", () => {
  it("renders nothing for null", () => {
    const { container } = render(<DeltaText value={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("signs the value and keeps it neutral", () => {
    render(
      <>
        <DeltaText value={18} />
        <DeltaText value={-4} unit=" days" />
      </>,
    );
    const up = screen.getByText("+18");
    expect(up.className).toContain("text-g600");
    expect(screen.getByText("-4 days")).toBeInTheDocument();
  });
});

describe("KpiTile", () => {
  it("shows label, value, delta and the previous caption", () => {
    render(<KpiTile label="Hires" value="3" delta={1} />);
    expect(screen.getByText("Hires")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("vs previous")).toBeInTheDocument();
  });

  it("draws no delta when it is null", () => {
    render(<KpiTile label="Hires" value="3" delta={null} />);
    expect(screen.queryByText("vs previous")).not.toBeInTheDocument();
  });

  it("shows a note instead of a delta", () => {
    render(<KpiTile label="Median time to hire" value="24" unit="days" note="n = 3" />);
    expect(screen.getByText("n = 3")).toBeInTheDocument();
  });

  it("appends the delta unit", () => {
    render(<KpiTile label="Median time to hire" value="24" delta={3} deltaUnit=" d" />);
    expect(screen.getByText("+3 d")).toBeInTheDocument();
  });
});
