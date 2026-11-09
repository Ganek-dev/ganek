import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { companyApi, type PlanOut } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale";

import { SettingsTabs } from "./SettingsTabs";

let pathname = "/admin/branding";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, companyApi: { ...original.companyApi, plan: vi.fn() } };
});

const mocked = vi.mocked(companyApi);

function plan(billing_enabled: boolean): PlanOut {
  return {
    plan: "free",
    billing_enabled,
    limits: { max_live_jobs: 1 },
    live_jobs: 0,
    over_limit: false,
    upgrade_url: null,
  };
}

describe("SettingsTabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pathname = "/admin/branding";
  });

  it("shows the Billing tab when the instance bills", async () => {
    mocked.plan.mockResolvedValue(plan(true));
    render(<SettingsTabs />);
    expect(await screen.findByRole("link", { name: "Billing" })).toHaveAttribute(
      "href",
      "/admin/billing",
    );
  });

  it("hides it on a self-hosted instance", async () => {
    mocked.plan.mockResolvedValue(plan(false));
    render(<SettingsTabs />);
    await screen.findByRole("link", { name: "Branding" });
    await Promise.resolve();
    expect(screen.queryByRole("link", { name: "Billing" })).toBeNull();
  });

  it("keeps the other tabs when the plan cannot be read", async () => {
    mocked.plan.mockRejectedValue(new Error("offline"));
    render(<SettingsTabs />);
    expect(await screen.findByRole("link", { name: "Developers" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Billing" })).toBeNull();
  });

  it("labels the tabs in the admin language", async () => {
    window.localStorage.setItem("ganek.admin.locale", "de");
    pathname = "/admin/account";
    mocked.plan.mockResolvedValue(plan(true));
    try {
      render(
        <LocaleProvider>
          <SettingsTabs />
        </LocaleProvider>,
      );
      expect(await screen.findByRole("link", { name: "Abrechnung" })).toHaveAttribute(
        "href",
        "/admin/billing",
      );
      expect(screen.getByRole("link", { name: "Konto" })).toHaveAttribute("aria-current", "page");
      expect(screen.getByRole("navigation", { name: "Einstellungsbereiche" })).toBeInTheDocument();
    } finally {
      window.localStorage.clear();
    }
  });
});
