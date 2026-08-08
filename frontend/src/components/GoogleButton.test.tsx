import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GoogleButton } from "./GoogleButton";

describe("GoogleButton", () => {
  it("links to the oauth start endpoint with the default label", () => {
    render(<GoogleButton />);
    const link = screen.getByRole("link", { name: "Continue with Google" });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start");
  });

  it("accepts a custom label", () => {
    render(<GoogleButton label="Sign up with Google" />);
    expect(screen.getByRole("link", { name: "Sign up with Google" })).toBeInTheDocument();
  });
});
