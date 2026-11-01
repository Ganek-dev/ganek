import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { stats, type BoardOut, type StatsOverview } from "@/lib/api";

import AdminDashboard from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, stats: { overview: vi.fn(), board: vi.fn() } };
});

const mocked = vi.mocked(stats);

const overview: StatsOverview = {
  jobs: { draft: 1, published: 3, closed: 2 },
  applications: { total: 25, new: 7, last_7_days: 4 },
  quiz: {
    attempts_total: 10,
    attempts_started: 10,
    attempts_completed: 8,
    completion_rate: 0.8,
    avg_score: 0.65,
    median_score: 0.71,
    avg_duration_seconds: 984,
    score_distribution: [0, 0, 1, 0, 0, 1, 2, 2, 1, 1],
  },
  per_job: [
    {
      job_id: "11111111-1111-1111-1111-111111111111",
      title: "Backend Engineer",
      status: "published",
      applications: 12,
      new: 5, views_30d: 0,
    },
  ],
  weekly: Array.from({ length: 8 }, (_, i) => ({
    week_start: `2026-06-0${i + 1}`,
    count: i * 100, // keep bar labels distinct from the stat-card numbers
  })),
  recent: [
    {
      id: "22222222-2222-2222-2222-222222222222",
      candidate_name: "Ada Lovelace",
      job_id: "11111111-1111-1111-1111-111111111111",
      job_title: "Backend Engineer",
      stage: "new",
      quiz_score: 0.75,
      created_at: "2026-07-20T10:00:00Z",
    },
  ],
};

const board: BoardOut = {
  stage_limit_days: 7,
  totals: { active_jobs: 5, live: 28, waiting_on_team: 12, overdue: 6, new_7d: 9 },
  jobs: [
    {
      job_id: "11111111-1111-1111-1111-111111111111",
      title: "Backend Engineer",
      job_status: "published",
      status: "stalled",
      live_by_stage: { new: 1, screening: 3, interview: 1, offer: 0 },
      waiting_on_team: 3,
      longest_wait_days: 11,
      overdue: 3,
      new_7d: 0,
      moved_7d: 0,
      days_open: 34,
      last_movement_at: null,
      reason: "No candidate moved in the last 7 days. 3 waiting on you.",
    },
    {
      job_id: "33333333-3333-3333-3333-333333333333",
      title: "Product Designer",
      job_status: "closed",
      status: "on_track",
      live_by_stage: { new: 0, screening: 1, interview: 0, offer: 0 },
      waiting_on_team: 0,
      longest_wait_days: null,
      overdue: 0,
      new_7d: 0,
      moved_7d: 1,
      days_open: 60,
      last_movement_at: null,
      reason: "Candidates are moving.",
    },
  ],
};

describe("AdminDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.overview.mockResolvedValue(overview);
    mocked.board.mockResolvedValue(board);
  });

  it("renders the five signal tiles from the board", async () => {
    render(<AdminDashboard />);

    const tiles = await screen.findByRole("group", { name: "Signals" });
    const t = within(tiles);
    expect(t.getByText("Active jobs")).toBeInTheDocument();
    expect(t.getByText("5")).toBeInTheDocument();
    expect(t.getByText("1 closed, still hiring")).toBeInTheDocument();
    expect(t.getByText("Live candidates")).toBeInTheDocument();
    expect(t.getByText("28")).toBeInTheDocument();
    expect(t.getByText("Waiting on you")).toBeInTheDocument();
    expect(t.getByText("12")).toBeInTheDocument();
    expect(t.getByText("Overdue")).toBeInTheDocument();
    expect(t.getByText("6")).toBeInTheDocument();
    expect(t.getByText("more than 7 days")).toBeInTheDocument();
    expect(t.getByText("New this week")).toBeInTheDocument();
    expect(t.getByText("9")).toBeInTheDocument();
    // the quiz tiles moved to Reports
    expect(screen.queryByText("Median quiz score")).toBeNull();
    expect(screen.queryByText("Quiz completion")).toBeNull();
  });

  it("renders the board and recent applicants", async () => {
    render(<AdminDashboard />);

    const table = await screen.findByRole("table", { name: "Open roles" });
    expect(within(table).getByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/admin/applicants?job=11111111-1111-1111-1111-111111111111",
    );
    expect(within(table).getByText("Closed")).toBeInTheDocument();

    // recent applicant with quiz badge, stage text neutral
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("quiz 75%")).toBeInTheDocument();
    const row = screen.getByText("Ada Lovelace").closest("li") as HTMLElement;
    const stage = within(row).getByText("new");
    expect(stage.getAttribute("style")).toBeNull();
    expect(stage.className).toContain("text-g600");

    // charts and the positions list left the dashboard
    expect(screen.queryByRole("img", { name: "Score distribution" })).toBeNull();
    expect(screen.queryByRole("img", { name: "Applications per week" })).toBeNull();
    expect(screen.queryByText("Positions")).toBeNull();
  });

  it("shows the error state", async () => {
    mocked.board.mockRejectedValue(new Error("nope"));
    render(<AdminDashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });
});
