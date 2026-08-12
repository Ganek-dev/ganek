import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { companyApi, type CompanyAdmin } from "@/lib/api";

import PrivacySettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/privacy",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: { get: vi.fn(), updateSettings: vi.fn() },
  };
});

const mocked = vi.mocked(companyApi);

function makeCompany(settings: CompanyAdmin["settings"] = {}): CompanyAdmin {
  return {
    slug: "acmelabs",
    name: "Acme Labs",
    description: "",
    logo_url: null,
    website: null,
    socials: {},
    theme: {},
    settings,
  };
}

describe("PrivacySettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(makeCompany());
    mocked.updateSettings.mockResolvedValue(makeCompany());
  });

  it("shows empty fields with the display-name fallback hint", async () => {
    render(<PrivacySettingsPage />);
    expect(await screen.findByLabelText("Legal entity name")).toHaveValue("");
    expect(screen.getByLabelText("Privacy contact email")).toHaveValue("");
    expect(screen.getByLabelText("Keep applications for")).toHaveValue("");
    expect(screen.getByText(/Empty = your display name/)).toBeInTheDocument();
  });

  it("hydrates stored settings", async () => {
    mocked.get.mockResolvedValue(
      makeCompany({
        legal_name: "Acme Labs Sp. z o.o.",
        privacy_contact_email: "privacy@acme.dev",
        retention_months: 12,
        privacy_policy_url: "https://acme.dev/privacy",
      }),
    );
    render(<PrivacySettingsPage />);
    expect(await screen.findByLabelText("Legal entity name")).toHaveValue("Acme Labs Sp. z o.o.");
    expect(screen.getByLabelText("Privacy contact email")).toHaveValue("privacy@acme.dev");
    expect(screen.getByLabelText("Keep applications for")).toHaveValue("12");
    expect(screen.getByLabelText("Policy URL")).toHaveValue("https://acme.dev/privacy");
  });

  it("saves trimmed values and nulls for cleared fields", async () => {
    const user = userEvent.setup();
    render(<PrivacySettingsPage />);
    await user.type(await screen.findByLabelText("Legal entity name"), "  Acme Labs GmbH  ");
    await user.type(screen.getByLabelText("Privacy contact email"), "privacy@acme.dev");
    await user.selectOptions(screen.getByLabelText("Keep applications for"), "12");
    await user.click(screen.getByRole("button", { name: "Save privacy settings" }));

    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({
        legal_name: "Acme Labs GmbH",
        privacy_contact_email: "privacy@acme.dev",
        retention_months: 12,
        privacy_policy_url: null,
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Privacy settings saved");
  });

  it("resets retention to default as null", async () => {
    mocked.get.mockResolvedValue(makeCompany({ retention_months: 12 }));
    const user = userEvent.setup();
    render(<PrivacySettingsPage />);
    await user.selectOptions(await screen.findByLabelText("Keep applications for"), "");
    await user.click(screen.getByRole("button", { name: "Save privacy settings" }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith(
        expect.objectContaining({ retention_months: null }),
      ),
    );
  });

  it("surfaces a save failure and keeps the form", async () => {
    mocked.updateSettings.mockRejectedValue(new Error("Enter a valid email address"));
    const user = userEvent.setup();
    render(<PrivacySettingsPage />);
    await user.type(await screen.findByLabelText("Privacy contact email"), "nope");
    await user.click(screen.getByRole("button", { name: "Save privacy settings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a valid email address");
    expect(screen.getByLabelText("Privacy contact email")).toHaveValue("nope");
  });

  it("links the public notice for this company", async () => {
    render(<PrivacySettingsPage />);
    expect(await screen.findByRole("link", { name: /View public notice/ })).toHaveAttribute(
      "href",
      "/c/acmelabs/privacy",
    );
  });
});
