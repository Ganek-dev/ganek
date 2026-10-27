import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  apiKeys,
  companyApi,
  publicJobsFeed,
  webhooks,
  type ApiKey,
  type JobsFeed,
} from "@/lib/api";

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
    apiKeys: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
    webhooks: { list: vi.fn(), create: vi.fn(), remove: vi.fn(), test: vi.fn() },
  };
});

const mockedCompany = vi.mocked(companyApi);
const mockedFeed = vi.mocked(publicJobsFeed);
const mockedKeys = vi.mocked(apiKeys);
const mockedHooks = vi.mocked(webhooks);

const feed: JobsFeed = {
  company: "Acme Labs",
  brand_primary: "#7E14FF",
  jobs: [
    {
      title: "Senior Frontend Engineer",
      slug: "senior-frontend-engineer",
      location: "Remote - Europe",
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
    mode: "single" as const,
    smtp_configured: true,
      name: "Acme Labs",
      description: "",
      logo_url: null,
      website: null,
      socials: {},
      theme: {},
      settings: {},
    });
    mockedFeed.mockResolvedValue(feed);
    mockedKeys.list.mockResolvedValue([]);
    mockedHooks.list.mockResolvedValue([]);
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
    expect(preview).toHaveTextContent("Careers powered by Ganek");
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

describe("API keys card", () => {
  const key: ApiKey = {
    id: "k1",
    name: "Zapier",
    prefix: "gk_abcdefghi",
    scope: "read",
    created_at: "2026-10-20T10:00:00Z",
    last_used_at: null,
    revoked_at: null,
  };

  beforeEach(() => {
    mockedKeys.list.mockResolvedValue([key]);
  });

  it("lists keys by prefix and scope and revokes with confirmation", async () => {
    mockedKeys.revoke.mockResolvedValue(undefined);
    render(<DevelopersPage />);
    const row = (await screen.findByText("Zapier")).closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("gk_abcdefghi")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("read")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Revoke Zapier" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke key" }));
    expect(mockedKeys.revoke).toHaveBeenCalledWith("k1");
  });

  it("creates a key and shows the secret exactly once", async () => {
    mockedKeys.create.mockResolvedValue({
      ...key,
      id: "k2",
      name: "ATS sync",
      prefix: "gk_zzzzzzzzz",
      scope: "write",
      secret: "gk_zzzzzzzzzSECRETSECRETSECRET",
    });
    render(<DevelopersPage />);
    await screen.findByText("Zapier");
    await userEvent.type(screen.getByLabelText("Key name"), "ATS sync");
    await userEvent.selectOptions(screen.getByLabelText("Scope"), "write");
    await userEvent.click(screen.getByRole("button", { name: "Create key" }));

    expect(mockedKeys.create).toHaveBeenCalledWith({ name: "ATS sync", scope: "write" });
    expect(await screen.findByText("gk_zzzzzzzzzSECRETSECRETSECRET")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy API key" })).toBeInTheDocument();
    expect(screen.getByText(/won't be shown again/i)).toBeInTheDocument();
  });
});
