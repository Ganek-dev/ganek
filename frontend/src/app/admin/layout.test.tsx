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
    api: { ...original.api, me: vi.fn(), logout: vi.fn(), providers: vi.fn() },
    companyApi: { ...original.companyApi, get: vi.fn(), usage: vi.fn() },
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
    mockedApi.providers.mockResolvedValue({ google: false, mode: "single" });
    mockedCompany.usage.mockResolvedValue({
      emails_today: 0,
      emails_per_day_limit: 500,
      applications_this_hour: 0,
      applications_per_hour_limit: 100,
      active_jobs: 1,
      active_jobs_limit: 50,
      warnings: [],
    });
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
        attempts_started: 0,
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

  it("shows a soft usage banner when a quota warning is reported", async () => {
    mockedCompany.usage.mockResolvedValue({
      emails_today: 420,
      emails_per_day_limit: 500,
      applications_this_hour: 3,
      applications_per_hour_limit: 100,
      active_jobs: 2,
      active_jobs_limit: 50,
      warnings: ["420 of 500 emails today"],
    });
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent("420 of 500 emails today");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows no banner when SMTP is configured or for members", async () => {
    const admin = render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    await screen.findByText("page content");
    // the admin company fetch runs in a later effect - let it land and
    // unmount before clearing, or it can count against the member render
    await waitFor(() => expect(mockedCompany.get).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    admin.unmount();

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

  it("shows Team and Settings to admins and hides them from members", async () => {
    const admin = render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    await screen.findByText("page content");
    expect(screen.getByRole("link", { name: /Team/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Settings/ })).toBeInTheDocument();
    admin.unmount();

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
    expect(screen.getByRole("link", { name: /Jobs/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Team/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Settings/ })).not.toBeInTheDocument();
  });

  it("shows a retryable error when the backend is unreachable", async () => {
    mockedApi.me.mockRejectedValueOnce(new TypeError("fetch failed"));
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    expect(await screen.findByText(/Can't reach the backend/)).toBeInTheDocument();
    expect(screen.queryByText("page content")).not.toBeInTheDocument();

    // retry re-arms the fetch; the default mock then succeeds
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("page content")).toBeInTheDocument();
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

  it("shows the demo strip and drops the SMTP warning on a demo instance", async () => {
    mockedApi.providers.mockResolvedValue({ google: false, mode: "single", demo: true });
    mockedCompany.get.mockResolvedValue({
      slug: "acme",
      name: "ACME Ganek",
      description: "",
      mode: "single",
      smtp_configured: false,
      logo_url: null,
      website: null,
      socials: {},
      theme: {},
      settings: {},
    } as CompanyAdmin);
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    expect(await screen.findByTestId("demo-banner")).toHaveTextContent("Demo workspace.");
    await waitFor(() => expect(mockedCompany.get).toHaveBeenCalled());
    expect(screen.queryByText(/Email is not configured on this instance/)).toBeNull();
  });
});
