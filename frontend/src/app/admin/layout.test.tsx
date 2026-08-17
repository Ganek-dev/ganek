import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, companyApi, stats, type CompanyAdmin } from "@/lib/api";

import AdminLayout from "./layout";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/admin/jobs",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, me: vi.fn(), logout: vi.fn() },
    companyApi: { ...original.companyApi, get: vi.fn() },
    stats: { overview: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);
const mockedCompany = vi.mocked(companyApi);
const mockedStats = vi.mocked(stats);

describe("AdminLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.me.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy@acme.dev",
      has_password: true,
      role: "admin",
    });
    mockedApi.logout.mockResolvedValue(undefined);
    mockedCompany.get.mockResolvedValue({
      slug: "acme",
      name: "Acme",
      description: "",
      mode: "single",
      smtp_configured: true,
      logo_url: null,
      website: null,
      socials: {},
      theme: {},
      settings: {},
    } as CompanyAdmin);
    mockedStats.overview.mockResolvedValue({
      jobs: { draft: 1, published: 3, closed: 0 },
      applications: { total: 10, new: 7, last_7_days: 2 },
      quiz: {
        attempts_total: 0,
        attempts_completed: 0,
        completion_rate: null,
        avg_score: null,
        median_score: null,
        avg_duration_seconds: null,
        score_distribution: [],
      },
      per_job: [],
      weekly: [],
      recent: [],
    });
  });

  it("renders sidebar nav with counters and marks the active item", async () => {
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    expect(await screen.findByText("page content")).toBeInTheDocument();

    const jobs = screen.getByRole("link", { name: /Jobs/ });
    expect(jobs).toHaveAttribute("aria-current", "page"); // pathname mock = /admin/jobs
    expect(screen.getByRole("link", { name: /Dashboard/ })).not.toHaveAttribute(
      "aria-current",
    );
    await waitFor(() => expect(jobs).toHaveTextContent("4")); // 3 published + 1 draft
    expect(screen.getByRole("link", { name: /Applicants/ })).toHaveTextContent("7");
    expect(screen.getByText("grumpy@acme.dev")).toBeInTheDocument();
  });

  it("warns admins when SMTP is unconfigured, and only then", async () => {
    const company = {
      slug: "acme",
      name: "Acme",
      description: "",
      mode: "single",
      smtp_configured: false,
      logo_url: null,
      website: null,
      socials: {},
      theme: {},
      settings: {},
    } as CompanyAdmin;
    mockedCompany.get.mockResolvedValue(company);
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/candidates are/i);
    expect(banner).toHaveTextContent(/not receiving/i);
  });

  it("shows no banner when SMTP is configured or for members", async () => {
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    await screen.findByText("page content");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // members never even fetch the admin-only company payload
    mockedCompany.get.mockClear();
    mockedApi.me.mockResolvedValue({
      id: "u2",
      company_id: "c1",
      email: "member@acme.dev",
      has_password: true,
      role: "member",
    });
    render(
      <AdminLayout>
        <p>member content</p>
      </AdminLayout>,
    );
    await screen.findByText("member content");
    expect(mockedCompany.get).not.toHaveBeenCalled();
  });

  it("signs out via the footer button", async () => {
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    await screen.findByText("page content");
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(mockedApi.logout).toHaveBeenCalled());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
