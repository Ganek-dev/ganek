import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoBanner } from "./DemoBanner";

describe("DemoBanner", () => {
  it("names the workspace as a demo that resets", () => {
    render(<DemoBanner />);
    const strip = screen.getByRole("status");
    expect(strip).toHaveTextContent("Demo workspace.");
    expect(strip).toHaveTextContent("Fictional data, resets nightly.");
    expect(strip).not.toHaveTextContent("Nothing you type");
  });

  it("tells candidates nothing they type is kept on the brand variant", () => {
    render(<DemoBanner tone="brand" />);
    const strip = screen.getByRole("status");
    expect(strip).toHaveTextContent("Nothing you type or upload here is kept.");
    expect(strip.className).toContain("bg-brand");
  });

  it("invites visitors to the recruiter side without printing any credential", () => {
    render(<DemoBanner tone="brand" />);
    const strip = screen.getByRole("status");
    expect(strip).toHaveTextContent("Curious about the recruiter side?");
    const link = screen.getByRole("link", { name: "Sign in with one click" });
    expect(link).toHaveAttribute("href", "/login");
    expect(strip.textContent).not.toMatch(/@|password|ganek-demo/i);
    expect(strip.textContent).not.toMatch(/[\u2013\u2014]/);
  });

  it("keeps the admin variant free of the sign-in invitation", () => {
    render(<DemoBanner />);
    expect(screen.queryByRole("link", { name: "Sign in with one click" })).not.toBeInTheDocument();
  });
});
