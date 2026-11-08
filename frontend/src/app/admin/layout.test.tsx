import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, companyApi, stats, type CompanyAdmin } from "@/lib/api";

import AdminLayout from "./layout";

const replace = vi.fn();
let pathname = "/admin/jobs";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => pathname,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, me: vi.fn(), logout: vi.fn(), providers: vi.fn() },
    companyApi: { ...original.companyApi, get: vi.fn(), usage: vi.fn(), plan: vi.fn() },
    stats: { overview: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);
const mockedCompany = vi.mocked(companyApi);
const mockedStats = vi.mocked(stats);

describe("AdminLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pathname = "/admin/jobs";
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
    mockedCompany.plan.mockResolvedValue({
      plan: "self_hosted",
      billing_enabled: false,
      limits: { max_live_jobs: null },
      live_jobs: 1,
      over_limit: false,
      upgrade_url: null,
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
    const applicants = screen.getByRole("link", { name: /Applicants/ });
    expect(applicants).toHaveTextContent("7 new");
    expect(applicants).toHaveAccessibleName("Applicants, 7 new applicants");
    expect(screen.getByText("grumpy@acme.dev")).toBeInTheDocument();
  });

  it("lists Reports directly after Applicants", async () => {
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    await screen.findByText("page content");
    const reports = screen.getByRole("link", { name: /Reports/ });
    expect(reports).toHaveAttribute("href", "/admin/reports");
    const links = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(links.indexOf("/admin/reports")).toBe(links.indexOf("/admin/applicants") + 1);
  });

  it("sends a reviewer session to /review and fires no staff calls", async () => {
    mockedApi.me.mockResolvedValue({
      id: "u2",
      company_id: "c1",
      email: "max@acme.example",
      has_password: true,
      role: "reviewer",
    });
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/review"));
    expect(screen.queryByText("page content")).not.toBeInTheDocument();
    expect(mockedStats.overview).not.toHaveBeenCalled();
    expect(mockedCompany.get).not.toHaveBeenCalled();
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

  it("tells an admin over the plan limit that nothing was closed, with the upgrade link", async () => {
    mockedCompany.plan.mockResolvedValue({
      plan: "free",
      billing_enabled: true,
      limits: { max_live_jobs: 1 },
      live_jobs: 3,
      over_limit: true,
      upgrade_url: "https://billing.example/upgrade",
    });
    render(
      <AdminLayout>
        <p>page content</p>
      </AdminLayout>,
    );
    const banner = await screen.findByTestId("plan-over-limit");
    expect(banner).toHaveTextContent("3 jobs are live and your plan allows 1.");
    expect(banner).toHaveTextContent("Nothing was closed");
    expect(screen.getByRole("link", { name: "Upgrade plan" })).toHaveAttribute(
      "href",
      "https://billing.example/upgrade",
    );
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

  describe("mobile top bar", () => {
    async function renderShell() {
      const view = render(
        <AdminLayout>
          <p>page content</p>
        </AdminLayout>,
      );
      await screen.findByText("page content");
      return view;
    }

    it("shows the menu button, wordmark and avatar, with the drawer closed", async () => {
      await renderShell();
      const open = screen.getByRole("button", { name: "Open navigation" });
      expect(open).toHaveAttribute("aria-expanded", "false");
      expect(open).toHaveAttribute("aria-controls", "admin-nav");
      const banner = screen.getByRole("banner");
      expect(banner).toHaveTextContent("Ganek.");
      expect(banner).toHaveTextContent("GR"); // initials of grumpy@acme.dev
      const drawer = document.getElementById("admin-nav");
      expect(drawer).toHaveClass("-translate-x-full", "max-md:invisible", "md:translate-x-0");
      expect(screen.queryByTestId("nav-backdrop")).not.toBeInTheDocument();
    });

    it("opens the drawer, focuses the first link and closes on Escape", async () => {
      const user = userEvent.setup();
      await renderShell();
      const open = screen.getByRole("button", { name: "Open navigation" });
      await user.click(open);
      expect(open).toHaveAttribute("aria-expanded", "true");
      const drawer = document.getElementById("admin-nav");
      expect(drawer).toHaveClass("translate-x-0");
      expect(drawer).not.toHaveClass("max-md:invisible");
      expect(screen.getByRole("link", { name: /Dashboard/ })).toHaveFocus();
      expect(document.body.style.overflow).toBe("hidden");

      await user.keyboard("{Escape}");
      expect(open).toHaveAttribute("aria-expanded", "false");
      expect(open).toHaveFocus();
      expect(document.body.style.overflow).toBe("");
    });

    it("closes from the close button, the backdrop and a nav link", async () => {
      const user = userEvent.setup();
      await renderShell();
      const open = screen.getByRole("button", { name: "Open navigation" });

      await user.click(open);
      await user.click(screen.getByRole("button", { name: "Close navigation" }));
      expect(open).toHaveAttribute("aria-expanded", "false");
      expect(open).toHaveFocus();

      await user.click(open);
      fireEvent.click(screen.getByTestId("nav-backdrop"));
      expect(open).toHaveAttribute("aria-expanded", "false");

      await user.click(open);
      fireEvent.click(screen.getByRole("link", { name: /Jobs/ }));
      expect(open).toHaveAttribute("aria-expanded", "false");
    });

    it("closes when the route changes", async () => {
      const user = userEvent.setup();
      const view = await renderShell();
      const open = screen.getByRole("button", { name: "Open navigation" });
      await user.click(open);
      expect(open).toHaveAttribute("aria-expanded", "true");

      pathname = "/admin/reports";
      view.rerender(
        <AdminLayout>
          <p>page content</p>
        </AdminLayout>,
      );
      expect(open).toHaveAttribute("aria-expanded", "false");
    });
  });
});
