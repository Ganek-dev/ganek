import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, stats } from "@/lib/api";

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
    stats: { overview: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);
const mockedStats = vi.mocked(stats);

describe("AdminLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.me.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy@acme.dev",
      role: "admin",
    });
    mockedApi.logout.mockResolvedValue(undefined);
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
