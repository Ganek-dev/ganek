import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { companyApi, publicJobsFeed, type JobsFeed } from "@/lib/api";

import DevelopersPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/developers",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: { get: vi.fn(), updateBranding: vi.fn(), updateSettings: vi.fn() },
    publicJobsFeed: vi.fn(),
  };
});

const mockedCompany = vi.mocked(companyApi);
const mockedFeed = vi.mocked(publicJobsFeed);

const feed: JobsFeed = {
  company: "Acme Labs",
  brand_primary: "#7E14FF",
  jobs: [
    {
      title: "Senior Frontend Engineer",
      slug: "senior-frontend-engineer",
      location: "Remote — Europe",
      remote_policy: "remote",
      employment_type: "full_time",
      tags: ["react", "typescript"],
      apply_url: "http://localhost/c/acmelabs/jobs/senior-frontend-engineer",
      posted_at: "2026-07-10T09:00:00Z",
    },
  ],
};

describe("DevelopersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedCompany.get.mockResolvedValue({
      slug: "acmelabs",
      name: "Acme Labs",
      description: "",
      logo_url: null,
      website: null,
      socials: {},
      theme: {},
      settings: {},
    });
    mockedFeed.mockResolvedValue(feed);
  });

  it("shows the feed URL, sample JSON, and live preview", async () => {
    render(<DevelopersPage />);
    expect(
      await screen.findByText(/\/api\/v1\/public\/companies\/acmelabs\/jobs-feed/),
    ).toBeInTheDocument();
    expect(screen.getByText("GET")).toBeInTheDocument();
    expect(screen.getByText(/Public, no auth, CORS enabled, cached 60s/)).toBeInTheDocument();
    const preview = await screen.findByTestId("widget-preview");
    expect(preview).toHaveTextContent("Senior Frontend Engineer");
    expect(preview).toHaveTextContent("1 role");
    expect(preview).toHaveTextContent("react");
    expect(preview).toHaveTextContent("Careers powered by vetd");
  });

  it("builds the snippet from theme and tags choices", async () => {
    render(<DevelopersPage />);
    const snippet = await screen.findByText(/data-workspace="acmelabs"/);
    expect(snippet.textContent).toContain('src="http://localhost:3000/embed/jobs.js"');
    expect(snippet.textContent).not.toContain("data-theme");
    expect(snippet.textContent).not.toContain("data-tags");

    await userEvent.click(screen.getByRole("radio", { name: "dark" }));
    expect(screen.getByText(/data-workspace/).textContent).toContain('data-theme="dark"');

    await userEvent.click(screen.getByRole("checkbox", { name: "Show tags" }));
    expect(screen.getByText(/data-workspace/).textContent).toContain('data-tags="false"');
    // hiding tags also hides them in the preview
    expect(screen.getByTestId("widget-preview")).not.toHaveTextContent("react");
  });

  it("shows the empty state when there are no published roles", async () => {
    mockedFeed.mockResolvedValue({ ...feed, jobs: [] });
    render(<DevelopersPage />);
    expect(await screen.findByText("No open positions right now.")).toBeInTheDocument();
    expect(screen.getByTestId("widget-preview")).toHaveTextContent("0 roles");
  });
});
