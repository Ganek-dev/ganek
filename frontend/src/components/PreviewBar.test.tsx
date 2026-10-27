import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PreviewBar } from "./PreviewBar";

describe("PreviewBar", () => {
  it("tells the viewer this is a preview that candidates cannot see", () => {
    render(<PreviewBar />);
    const strip = screen.getByRole("status");
    expect(strip).toHaveTextContent("Preview, not live.");
    expect(strip).toHaveTextContent("Candidates cannot see this page until the job is published.");
    expect(strip.className).toContain("bg-brand");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(strip.textContent).not.toMatch(/[\u2013\u2014]/);
  });
});
