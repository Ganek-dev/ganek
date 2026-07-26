import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, stats, type JobOut, type StatsOverview } from "@/lib/api";

import JobsPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      jobs: { ...original.api.jobs, list: vi.fn(), publish: vi.fn(), close: vi.fn(), delete: vi.fn() },
    },
    stats: { overview: vi.fn() },
  };
});

const mockedJobs = vi.mocked(api.jobs);
const mockedStats = vi.mocked(stats);

const LIVE_ID = "11111111-1111-1111-1111-111111111111";
const DRAFT_ID = "22222222-2222-2222-2222-222222222222";
const CLOSED_ID = "33333333-3333-3333-3333-333333333333";

function makeJob(overrides: Partial<JobOut>): JobOut {
  return {
    id: LIVE_ID,
    slug: "job",
    title: "Job",
    description_md: "",
    location: "",
    remote_policy: "remote",
    employment_type: "full_time",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    tags: [],
    status: "published",
    quiz_config: {
      enabled: false,
      tags: null,
      question_count: 6,
      include_company_questions: true,
      time_limit_seconds: 20,
      difficulties: null,
      exclude_ids: [],
    },
    published_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function makeOverview(perJob: StatsOverview["per_job"]): StatsOverview {
  return {
    jobs: { draft: 1, published: 1, closed: 1 },
    applications: { total: 0, new: 0, last_7_days: 0 },
    quiz: {
      attempts_total: 0,
      attempts_completed: 0,
      completion_rate: null,
      avg_score: null,
      median_score: null,
      avg_duration_seconds: null,
      score_distribution: Array(10).fill(0),
    },
    per_job: perJob,
    weekly: [],
    recent: [],
  };
}

describe("JobsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedJobs.list.mockResolvedValue([
      makeJob({
        id: LIVE_ID,
        title: "Live role",
        status: "published",
        tags: ["python", "fastapi", "sql", "docker"],
        quiz_config: {
          enabled: true,
          tags: null,
          question_count: 12,
          include_company_questions: true,
          time_limit_seconds: 25,
          difficulties: null,
          exclude_ids: [],
        },
        published_at: "2026-07-12T00:00:00Z",
      }),
      makeJob({ id: DRAFT_ID, title: "Draft role", status: "draft" }),
      makeJob({ id: CLOSED_ID, title: "Old role", status: "closed" }),
    ]);
    mockedStats.overview.mockResolvedValue(
      makeOverview([
        { job_id: LIVE_ID, title: "Live role", status: "published", applications: 12, new: 7 },
        { job_id: DRAFT_ID, title: "Draft role", status: "draft", applications: 0, new: 0 },
        { job_id: CLOSED_ID, title: "Old role", status: "closed", applications: 3, new: 0 },
      ]),
    );
  });

  it("shows all jobs by default and filters via status pills with counts", async () => {
    render(<JobsPage />);
    expect(await screen.findByText("Live role")).toBeInTheDocument();
    expect(screen.getByText("Draft role")).toBeInTheDocument();
    expect(screen.getByText("Old role")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All · 3" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open · 1" }));
    expect(screen.getByText("Live role")).toBeInTheDocument();
    expect(screen.queryByText("Old role")).not.toBeInTheDocument();
    expect(screen.queryByText("Draft role")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Closed · 1" }));
    expect(screen.queryByText("Live role")).not.toBeInTheDocument();
    expect(screen.getByText("Old role")).toBeInTheDocument();
  });

  it("filters by search query across title and tags", async () => {
    render(<JobsPage />);
    await screen.findByText("Live role");

    await userEvent.type(screen.getByRole("textbox", { name: "Search jobs" }), "draft ro");
    expect(screen.getByText("Draft role")).toBeInTheDocument();
    expect(screen.queryByText("Live role")).not.toBeInTheDocument();

    await userEvent.clear(screen.getByRole("textbox", { name: "Search jobs" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Search jobs" }), "python");
    expect(screen.getByText("Live role")).toBeInTheDocument();
    expect(screen.queryByText("Draft role")).not.toBeInTheDocument();
  });

  it("renders applicant counts with the new-applicants accent", async () => {
    render(<JobsPage />);
    const row = (await screen.findByText("Live role")).closest("tr")!;
    expect(within(row).getByText("12")).toBeInTheDocument();
    expect(within(row).getByText("+7 new")).toBeInTheDocument();

    const closedRow = screen.getByText("Old role").closest("tr")!;
    expect(within(closedRow).getByText("3")).toBeInTheDocument();
    expect(within(closedRow).queryByText(/new/)).not.toBeInTheDocument();
  });

  it("shows assessment chips: config summary, no-quiz nudge, off", async () => {
    render(<JobsPage />);
    const live = (await screen.findByText("Live role")).closest("tr")!;
    expect(within(live).getByText("12q · 25s")).toBeInTheDocument();

    const draft = screen.getByText("Draft role").closest("tr")!;
    expect(within(draft).getByText("assessment off")).toBeInTheDocument();
  });

  it("shows the amber no-quiz nudge for published jobs without assessment", async () => {
    mockedJobs.list.mockResolvedValue([
      makeJob({ id: LIVE_ID, title: "Live role", status: "published" }),
    ]);
    render(<JobsPage />);
    const row = (await screen.findByText("Live role")).closest("tr")!;
    expect(within(row).getByText("no quiz yet")).toBeInTheDocument();
  });

  it("shows tag chips with overflow counter and posted date", async () => {
    render(<JobsPage />);
    const row = (await screen.findByText("Live role")).closest("tr")!;
    expect(within(row).getByText("python")).toBeInTheDocument();
    expect(within(row).getByText("+1")).toBeInTheDocument();
    expect(within(row).getByText("Jul 12")).toBeInTheDocument();
  });

  it("publishes a draft from the row actions menu", async () => {
    mockedJobs.publish.mockResolvedValue(makeJob({ id: DRAFT_ID, status: "published" }));
    render(<JobsPage />);
    await screen.findByText("Draft role");

    await userEvent.click(screen.getByRole("button", { name: "Actions for Draft role" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Edit" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();

    await userEvent.click(within(menu).getByRole("menuitem", { name: "Publish" }));
    expect(mockedJobs.publish).toHaveBeenCalledWith(DRAFT_ID);
    // menu closes and jobs reload after the action
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(mockedJobs.list).toHaveBeenCalledTimes(2);
  });

  it("offers Close instead of Publish for published jobs", async () => {
    render(<JobsPage />);
    await screen.findByText("Live role");

    await userEvent.click(screen.getByRole("button", { name: "Actions for Live role" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Close" })).toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: "Publish" })).not.toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("still renders the table when stats are unavailable", async () => {
    mockedStats.overview.mockRejectedValue(new Error("boom"));
    render(<JobsPage />);
    const row = (await screen.findByText("Live role")).closest("tr")!;
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });
});
