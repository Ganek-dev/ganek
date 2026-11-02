import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { reportsFixture } from "./reportsFixture";
import { SourcesTable } from "./SourcesTable";

describe("SourcesTable", () => {
  it("lists direct first and computes the interview percent", () => {
    render(<SourcesTable rows={reportsFixture.sources} />);
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveAccessibleName("direct 58 14 24 2");
    expect(rows[2]).toHaveAccessibleName("linkedin 41 8 20 1");
    expect(rows[3]).toHaveAccessibleName("indeed 23 4 17 0");
  });

  it("keeps the order when there is no direct row", () => {
    render(<SourcesTable rows={reportsFixture.sources.slice(0, 1)} />);
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("says so when empty", () => {
    render(<SourcesTable rows={[]} />);
    expect(screen.getByText("No applications in this period.")).toBeInTheDocument();
  });
});
