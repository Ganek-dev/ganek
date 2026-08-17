import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { companyApi, type CompanyAdmin } from "@/lib/api";

import HiringSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/hiring",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: { get: vi.fn(), updateBranding: vi.fn(), updateSettings: vi.fn() },
  };
});

const mocked = vi.mocked(companyApi);

function makeCompany(settings: CompanyAdmin["settings"] = {}): CompanyAdmin {
  return {
    slug: "acmelabs",
    mode: "single" as const,
    smtp_configured: true,
    name: "Acme Labs",
    description: "",
    logo_url: null,
    website: null,
    socials: {},
    theme: {},
    settings,
  };
}

describe("HiringSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(makeCompany());
    mocked.updateSettings.mockResolvedValue(makeCompany({ quiz_expired_reissue: "auto" }));
  });

  it("defaults to manual when no setting is stored", async () => {
    render(<HiringSettingsPage />);
    expect(await screen.findByRole("radio", { name: /Ask the team first/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("hydrates a stored auto setting", async () => {
    mocked.get.mockResolvedValue(makeCompany({ quiz_expired_reissue: "auto" }));
    render(<HiringSettingsPage />);
    expect(
      await screen.findByRole("radio", { name: /Re-issue automatically/ }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("saves auto, and manual as null (reset to default)", async () => {
    render(<HiringSettingsPage />);
    await userEvent.click(await screen.findByRole("radio", { name: /Re-issue automatically/ }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({ quiz_expired_reissue: "auto" }),
    );
    await userEvent.click(screen.getByRole("radio", { name: /Ask the team first/ }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({ quiz_expired_reissue: null }),
    );
  });

  it("rolls the selection back when saving fails", async () => {
    mocked.updateSettings.mockRejectedValue(new Error("boom"));
    render(<HiringSettingsPage />);
    await userEvent.click(await screen.findByRole("radio", { name: /Re-issue automatically/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByRole("radio", { name: /Ask the team first/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});
