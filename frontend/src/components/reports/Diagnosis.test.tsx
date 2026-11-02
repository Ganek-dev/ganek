import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Diagnosis } from "./Diagnosis";

describe("Diagnosis", () => {
  it("shows every line verbatim", () => {
    render(<Diagnosis lines={["Most candidates leave between A and B: 35 percent move on.", "Second."]} />);
    expect(
      screen.getByText("Most candidates leave between A and B: 35 percent move on."),
    ).toBeInTheDocument();
    expect(screen.getByText("Second.")).toBeInTheDocument();
  });

  it("shows the not-enough-data line for a small cohort", () => {
    render(<Diagnosis lines={["Not enough data yet (6 applications)"]} />);
    expect(screen.getByText("Not enough data yet (6 applications)")).toBeInTheDocument();
  });

  it("renders nothing without lines", () => {
    const { container } = render(<Diagnosis lines={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
