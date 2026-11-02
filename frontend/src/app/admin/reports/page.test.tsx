import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { reportsFixture } from "@/components/reports/reportsFixture";
import { stats, type ReportsOut, type StatsOverview } from "@/lib/api";

import ReportsPage from "./page";

let search = new URLSearchParams();
const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/reports",
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => search,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, stats: { overview: vi.fn(), board: vi.fn(), reports: vi.fn() } };
});

const mocked = vi.mocked(stats);

const overview = {
  per_job: [
    { job_id: "j-draft", title: "Draft role", status: "draft", applications: 0, new: 0, views_30d: 0 },
    { job_id: "j-1", title: "Backend Engineer", status: "published", applications: 5, new: 1, views_30d: 0 },
  ],
} as unknown as StatsOverview;

beforeEach(() => {
  vi.clearAllMocks();
  search = new URLSearchParams();
  mocked.overview.mockResolvedValue(overview);
  mocked.reports.mockResolvedValue(reportsFixture);
});

describe("ReportsPage", () => {
  it("reads period and job from the URL and updates them", async () => {
    search = new URLSearchParams("period=12m&job=j-1");
    render(<ReportsPage />);
    await screen.findByRole("heading", { name: "Funnel" });
    expect(mocked.reports).toHaveBeenCalledWith({ period: "12m", job_id: "j-1" });
    expect(screen.getByRole("radio", { name: "12 months" })).toBeChecked();

    await userEvent.click(screen.getByRole("radio", { name: "30 days" }));
    expect(replace).toHaveBeenCalledWith("/admin/reports?period=30d&job=j-1", { scroll: false });
  });

  it("defaults to 90 days and all jobs, keeping the URL clean", async () => {
    render(<ReportsPage />);
    await screen.findByRole("heading", { name: "Funnel" });
    expect(mocked.reports).toHaveBeenCalledWith({ period: "90d", job_id: undefined });
    await userEvent.selectOptions(screen.getByLabelText("Job"), "j-1");
    expect(replace).toHaveBeenCalledWith("/admin/reports?job=j-1", { scroll: false });
  });

  it("lists the jobs from the overview, drafts last", async () => {
    render(<ReportsPage />);
    await screen.findByRole("heading", { name: "Funnel" });
    await waitFor(() =>
      expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
        "All jobs",
        "Backend Engineer",
        "Draft role (draft)",
      ]),
    );
  });

  it("keeps the report when the overview fails", async () => {
    mocked.overview.mockRejectedValue(new Error("boom"));
    render(<ReportsPage />);
    await screen.findByRole("heading", { name: "Funnel" });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["All jobs"]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders four tiles with deltas and no delta when previous is null", async () => {
    const { unmount } = render(<ReportsPage />);
    const tiles = await screen.findByRole("group", { name: "Headline numbers" });
    expect(within(tiles).getByText("142")).toBeInTheDocument();
    expect(within(tiles).getByText("+18")).toBeInTheDocument();
    expect(within(tiles).getByText("-4")).toBeInTheDocument();
    expect(within(tiles).getByText("+1")).toBeInTheDocument();
    // previous median is null: no delta, the previous n is shown
    expect(within(tiles).getByText("n = 3 · previous - (n = 2)")).toBeInTheDocument();
    unmount();

    mocked.reports.mockResolvedValue({ ...reportsFixture, period: "all", previous: null });
    render(<ReportsPage />);
    const again = await screen.findByRole("group", { name: "Headline numbers" });
    expect(within(again).queryByText("vs previous")).not.toBeInTheDocument();
    expect(within(again).queryByText(/previous/)).not.toBeInTheDocument();
  });

  it("shows a delta for the median when both are known", async () => {
    mocked.reports.mockResolvedValue({
      ...reportsFixture,
      previous: { ...reportsFixture.previous!, hires_n: 4, median_time_to_hire_days: 30 },
    });
    render(<ReportsPage />);
    const tiles = await screen.findByRole("group", { name: "Headline numbers" });
    expect(within(tiles).getByText("-6 d")).toBeInTheDocument();
  });

  it("shows a dash for a null median", async () => {
    mocked.reports.mockResolvedValue({
      ...reportsFixture,
      cohort: { ...reportsFixture.cohort, median_time_to_hire_days: null, hires_n: 2 },
    });
    render(<ReportsPage />);
    const tiles = await screen.findByRole("group", { name: "Headline numbers" });
    expect(within(tiles).getByText("n = 2 · previous - (n = 2)")).toBeInTheDocument();
    expect(within(tiles).queryByText("days")).not.toBeInTheDocument();
  });

  it("renders the funnel bars, pass-through text, split counts and the table", async () => {
    render(<ReportsPage />);
    await screen.findByRole("heading", { name: "Funnel" });
    expect(screen.getByRole("img", { name: /^Funnel: Applied 142, 62 percent move on/ })).toBeInTheDocument();
    expect(screen.getAllByText("View as table", { selector: "summary" }).length).toBeGreaterThan(0);
    expect(screen.getByText("Quiz: 120 invited, 97 completed (81 percent), 14 expired")).toBeInTheDocument();
    expect(screen.getByText("Candidates wait longest in Screening: median 9 days (n = 78).")).toBeInTheDocument();
  });

  it("renders the not-enough-data line for a small cohort", async () => {
    mocked.reports.mockResolvedValue({
      ...reportsFixture,
      diagnosis: ["Not enough data yet (6 applications)"],
    });
    render(<ReportsPage />);
    expect(await screen.findByText("Not enough data yet (6 applications)")).toBeInTheDocument();
  });

  it("renders time in stage with n and oldest live", async () => {
    render(<ReportsPage />);
    expect(await screen.findByText("oldest live candidate: 18 d")).toBeInTheDocument();
    expect(screen.getAllByText("(n = 78)").length).toBeGreaterThan(0);
  });

  it("renders sources with direct first and the interview percent", async () => {
    render(<ReportsPage />);
    await screen.findByRole("heading", { name: "Sources" });
    expect(screen.getByRole("row", { name: "direct 58 14 24 2" })).toBeInTheDocument();
  });

  it("moves score distribution and the weekly chart here without a pass line", async () => {
    render(<ReportsPage />);
    expect(await screen.findByRole("img", { name: /^Score distribution/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /^Applications per week/ })).toBeInTheDocument();
    expect(screen.queryByText(/pass rate|pass ≥/i)).not.toBeInTheDocument();
  });

  it("shows a loading skeleton, then an inline error", async () => {
    let reject!: (e: Error) => void;
    mocked.reports.mockReturnValue(new Promise<ReportsOut>((_, r) => (reject = r)));
    render(<ReportsPage />);
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
    reject(new Error("Could not load reports"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load reports");
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it("ignores a stale response after the period changes", async () => {
    let resolveFirst!: (r: ReportsOut) => void;
    mocked.reports
      .mockReturnValueOnce(new Promise<ReportsOut>((r) => (resolveFirst = r)))
      .mockResolvedValue({ ...reportsFixture, cohort: { ...reportsFixture.cohort, applications: 777 } });
    const { rerender } = render(<ReportsPage />);
    search = new URLSearchParams("period=30d");
    rerender(<ReportsPage />);
    await screen.findByText("777");
    resolveFirst({ ...reportsFixture, cohort: { ...reportsFixture.cohort, applications: 555 } });
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.getByText("777")).toBeInTheDocument();
    expect(screen.queryByText("555")).not.toBeInTheDocument();
  });
});
