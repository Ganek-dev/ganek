import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SsoButton } from "./SsoButton";

describe("SsoButton", () => {
  it("links to the start endpoint with the provider name as its label", () => {
    render(<SsoButton name="Keycloak" href="/api/v1/auth/oidc/start" />);
    expect(screen.getByRole("link", { name: "Continue with Keycloak" })).toHaveAttribute(
      "href",
      "/api/v1/auth/oidc/start",
    );
  });
});
