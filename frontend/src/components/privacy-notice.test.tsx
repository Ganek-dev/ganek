import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PublicPrivacyNotice } from "@/lib/public-api";

import { PrivacyNotice } from "./privacy-notice";

function makeNotice(overrides: Partial<PublicPrivacyNotice> = {}): PublicPrivacyNotice {
  return {
    company_name: "Acme Labs",
    legal_name: "Acme Labs",
    privacy_contact_email: null,
    retention_months: 6,
    privacy_policy_url: null,
    brand_primary: null,
    logo_url: null,
    ...overrides,
  };
}

describe("PrivacyNotice", () => {
  it("names the controller and the retention period", () => {
    render(
      <PrivacyNotice
        notice={makeNotice({ legal_name: "Acme Labs Sp. z o.o.", retention_months: 12 })}
        backHref="/c/acme"
      />,
    );
    expect(screen.getByText("Acme Labs Sp. z o.o.")).toBeInTheDocument();
    expect(screen.getByText("12 months")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Back to careers" })).toHaveAttribute(
      "href",
      "/c/acme",
    );
  });

  it("singularizes one month", () => {
    render(<PrivacyNotice notice={makeNotice({ retention_months: 1 })} backHref="/" />);
    expect(screen.getByText("1 month")).toBeInTheDocument();
  });

  it("discloses the complete integrity-signal list, pastes included", () => {
    render(<PrivacyNotice notice={makeNotice()} backHref="/" />);
    const signals = screen.getByText(/tab switches \(with how long you were away\)/);
    expect(signals.textContent).toContain("pastes");
    expect(signals.textContent).toContain("window resizes");
    expect(signals.textContent).toContain("tied to the question that was open");
  });

  it("links the privacy contact when set, falls back when not", () => {
    const { unmount } = render(
      <PrivacyNotice
        notice={makeNotice({ privacy_contact_email: "privacy@acme.dev" })}
        backHref="/"
      />,
    );
    expect(screen.getByRole("link", { name: "privacy@acme.dev" })).toHaveAttribute(
      "href",
      "mailto:privacy@acme.dev",
    );
    unmount();
    render(<PrivacyNotice notice={makeNotice()} backHref="/" />);
    expect(screen.getByText(/contact Acme Labs directly/)).toBeInTheDocument();
  });

  it("shows the own-policy card only when a URL is set", () => {
    const { unmount } = render(
      <PrivacyNotice
        notice={makeNotice({ privacy_policy_url: "https://acme.dev/privacy" })}
        backHref="/"
      />,
    );
    expect(
      screen.getByRole("link", { name: /maintains its own privacy policy/ }),
    ).toHaveAttribute("href", "https://acme.dev/privacy");
    unmount();
    render(<PrivacyNotice notice={makeNotice()} backHref="/" />);
    expect(screen.queryByRole("link", { name: /maintains its own privacy policy/ })).toBeNull();
  });

  it("states the no-auto-reject and no-tracker guarantees", () => {
    render(<PrivacyNotice notice={makeNotice()} backHref="/" />);
    expect(screen.getByText(/no one is rejected by a machine/)).toBeInTheDocument();
    expect(screen.getByText(/sets no cookies and runs no analytics/)).toBeInTheDocument();
  });
});
