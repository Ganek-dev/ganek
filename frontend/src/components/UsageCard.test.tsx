import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { companyApi, type CompanyAdmin, type UsageOut } from "@/lib/api";

import { UsageCard } from "./UsageCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: { ...original.companyApi, get: vi.fn(), usage: vi.fn() },
  };
});

const mocked = vi.mocked(companyApi);

const company: CompanyAdmin = {
  slug: "acme",
  name: "Acme",
  description: "",
  mode: "multi",
  smtp_configured: true,
  logo_url: null,
  website: null,
  socials: {},
  theme: {},
  settings: {},
};

const usage: UsageOut = {
  emails_today: 12,
  emails_per_day_limit: 500,
  applications_this_hour: 0,
  applications_per_hour_limit: 100,
  active_jobs: 3,
  active_jobs_limit: 50,
  warnings: [],
};

describe("UsageCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(company);
    mocked.usage.mockResolvedValue(usage);
  });

  it("shows the three counters against their limits in multi mode", async () => {
    render(<UsageCard />);
    expect(await screen.findByRole("heading", { name: "Usage and limits" })).toBeInTheDocument();
    expect(screen.getByText("Open jobs")).toBeInTheDocument();
    expect(screen.getByText("3 of 50")).toBeInTheDocument();
    expect(screen.getByText("Applications this hour")).toBeInTheDocument();
    expect(screen.getByText("0 of 100")).toBeInTheDocument();
    expect(screen.getByText("Candidate emails today")).toBeInTheDocument();
    expect(screen.getByText("12 of 500")).toBeInTheDocument();
    // meters are real progressbars so the fill is queryable, not decoration
    expect(screen.getByRole("progressbar", { name: "Open jobs" })).toHaveAttribute(
      "aria-valuenow",
      "3",
    );
  });

  it("says no limit for a guard that is off", async () => {
    mocked.usage.mockResolvedValue({ ...usage, emails_per_day_limit: 0 });
    render(<UsageCard />);
    expect(await screen.findByText("12, no limit")).toBeInTheDocument();
    expect(
      screen.queryByRole("progressbar", { name: "Candidate emails today" }),
    ).not.toBeInTheDocument();
  });

  it("stays hidden on a single-company instance", async () => {
    mocked.get.mockResolvedValue({ ...company, mode: "single" });
    const { container } = render(<UsageCard />);
    await waitFor(() => expect(mocked.get).toHaveBeenCalled());
    expect(mocked.usage).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the counters cannot be loaded", async () => {
    mocked.usage.mockRejectedValue(new Error("boom"));
    const { container } = render(<UsageCard />);
    await waitFor(() => expect(mocked.usage).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
