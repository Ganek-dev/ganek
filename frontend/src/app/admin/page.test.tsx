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
  quiz: { attempts_total: 10, attempts_completed: 8, completion_rate: 0.8, avg_score: 0.65 },
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

    expect(await screen.findByText("Open positions")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // published jobs
    expect(screen.getByText("1 draft · 2 closed")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument(); // new applicants
    expect(screen.getByText("80%")).toBeInTheDocument(); // completion
    expect(screen.getByText("avg score 65%")).toBeInTheDocument();

    // per-job row with new badge
    expect(screen.getByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/admin/jobs/11111111-1111-1111-1111-111111111111",
    );
    expect(screen.getByText("5 new")).toBeInTheDocument();

    // recent applicant with quiz badge
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("quiz 75%")).toBeInTheDocument();

    // weekly chart present
    expect(screen.getByRole("img", { name: "Applications per week" })).toBeInTheDocument();
  });

  it("shows an error state", async () => {
    mocked.overview.mockRejectedValue(new Error("nope"));
    render(<AdminDashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });
});
