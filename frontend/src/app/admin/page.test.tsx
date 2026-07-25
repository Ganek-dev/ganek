import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { stats, type StatsOverview } from "@/lib/api";

import AdminDashboard from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, stats: { overview: vi.fn() } };
});

const mocked = vi.mocked(stats);

const overview: StatsOverview = {
  jobs: { draft: 1, published: 3, closed: 2 },
  applications: { total: 25, new: 7, last_7_days: 4 },
  quiz: {
    attempts_total: 10,
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
      new: 5,
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

describe("AdminDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.overview.mockResolvedValue(overview);
  });

  it("renders stat cards, positions, and recent applicants", async () => {
    render(<AdminDashboard />);

    expect(await screen.findByText("Active jobs")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // published jobs
    expect(screen.getByText("1 draft · 2 closed")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument(); // awaiting review
    expect(screen.getByText("▲ 4 this week")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument(); // completion
    expect(screen.getByText("8 of 10 attempts")).toBeInTheDocument();

    // per-job row with new badge
    expect(screen.getByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/admin/jobs/11111111-1111-1111-1111-111111111111",
    );
    expect(screen.getByText("5 new")).toBeInTheDocument();

    // recent applicant with quiz badge
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("quiz 75%")).toBeInTheDocument();

    // charts present
    expect(screen.getByRole("img", { name: "Score distribution" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Applications per week" })).toBeInTheDocument();
  });

  it("shows median, pass rate and avg time under the distribution", async () => {
    render(<AdminDashboard />);
    await screen.findByText("Score distribution");

    expect(screen.getByText("71%")).toBeInTheDocument(); // median stat card
    expect(screen.getByText("71")).toBeInTheDocument(); // median under chart
    // pass rate: buckets >= 0.6 are 2+2+1+1 = 6 of 8 completed
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("16:24")).toBeInTheDocument(); // 984s avg time
    expect(screen.getByText(/pass ≥ 60/)).toBeInTheDocument(); // visualization-only marker
  });

  it("shows an empty distribution state without bars", async () => {
    mocked.overview.mockResolvedValue({
      ...overview,
      quiz: {
        ...overview.quiz,
        attempts_completed: 0,
        score_distribution: Array(10).fill(0) as number[],
      },
    });
    render(<AdminDashboard />);
    expect(await screen.findByText("No completed assessments yet.")).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    mocked.overview.mockRejectedValue(new Error("nope"));
    render(<AdminDashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });
});
