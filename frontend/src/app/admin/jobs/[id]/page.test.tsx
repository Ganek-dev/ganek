import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  applications,
  companyApi,
  type ApplicationOut,
  type CompanyAdmin,
  type JobOut,
  type JobStats,
} from "@/lib/api";

import JobOverviewPage from "./page";

const JOB_ID = "11111111-1111-1111-1111-111111111111";
const APP_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const APP_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ id: "11111111-1111-1111-1111-111111111111" }),
}));

vi.mock("@/components/QuizPreviewPanel", () => ({
  QuizPreviewPanel: () => <div>quiz preview</div>,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      jobs: {
        ...original.api.jobs,
        get: vi.fn(),
        stats: vi.fn(),
        publish: vi.fn(),
        close: vi.fn(),
        previewLink: vi.fn(),
      },
    },
    applications: { ...original.applications, list: vi.fn() },
    // the overview must not depend on the admin-only company view: a member
    // (recruiter) sees the public link and the share links too
    companyApi: { ...original.companyApi, get: vi.fn(), summary: vi.fn() },
  };
});

const mockedJobs = vi.mocked(api.jobs);
const mockedApplications = vi.mocked(applications);
const mockedCompany = vi.mocked(companyApi);

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: JOB_ID,
    slug: "senior-frontend-engineer",
    title: "Senior Frontend Engineer",
    description_md: "",
    location: "",
    remote_policy: "remote",
    employment_type: "full_time",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: "year",
    closes_at: null,
    tags: ["react"],
    status: "published",
    quiz_config: {
      enabled: true,
      tags: null,
      question_count: 12,
      include_company_questions: true,
      time_limit_seconds: 25,
      difficulties: null,
      exclude_ids: [],
      questionnaire_id: null,
    },
    published_at: "2026-07-10T00:00:00Z",
    closed_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function makeStats(overrides: Partial<JobStats> = {}): JobStats {
  return {
    applications: { total: 5, new: 2, last_7_days: 3 },
    views: { total: 3410, last_30_days: 1204 },
    views_by_source: { linkedin: 40, "ref:tiny.example": 2 },
    daily: Array.from({ length: 30 }, (_, i) => ({
      day: `2026-07-${String(i + 1).padStart(2, "0")}`,
      views: i,
      applications: i % 10 === 9 ? 1 : 0,
    })),
    last_30_days: 3,
    by_stage: { new: 2, screening: 1, hired: 2 },
    by_source: { linkedin: 3, direct: 2 },
    quiz: {
      attempts_total: 3,
      attempts_started: 3,
      attempts_completed: 2,
      completion_rate: 2 / 3,
      avg_score: 0.7,
      median_score: 0.75,
      avg_duration_seconds: 300,
      score_distribution: Array(10).fill(0),
    },
    weekly: Array.from({ length: 8 }, (_, i) => ({ week_start: `2026-0${i + 1}-01`, count: i })),
    days_open: 12,
    ...overrides,
  };
}

function makeApplication(overrides: Partial<ApplicationOut>): ApplicationOut {
  return {
    id: APP_A,
    job_id: JOB_ID,
    candidate: { id: "c1", name: "Marta Vidal", email: "marta@example.com", links: {} },
    cv_filename: "marta.pdf",
    cv_size: 1024,
    message: null,
    stage: "new",
    source: null,
    quiz_attempt: null,
    created_at: "2026-07-15T00:00:00Z",
    ...overrides,
  };
}

const company = { slug: "acme", name: "ACME", mode: "multi" } as CompanyAdmin;

describe("JobOverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedJobs.get.mockResolvedValue(makeJob());
    mockedJobs.stats.mockResolvedValue(makeStats());
    mockedCompany.get.mockRejectedValue(new Error("403 admin only"));
    mockedCompany.summary.mockResolvedValue({
      slug: company.slug,
      name: company.name,
      mode: company.mode,
    });
    mockedJobs.previewLink.mockResolvedValue({
      url: "http://localhost:3000/c/acme/jobs/senior-frontend-engineer?preview=default",
      expires_at: "2026-11-02T00:00:00Z",
    });
    mockedApplications.list.mockResolvedValue({
      items: [
        makeApplication({
          id: APP_A,
          quiz_attempt: {
            status: "completed",
            score: 0.75,
            per_tag_scores: {},
            completed_at: "2026-07-16T00:00:00Z",
            question_ids: [],
            time_multiplier: 1,
            integrity: { flags: [{ code: "blur", summary: "left the tab", detail: "", question_ids: [] }] },
          },
          source: "linkedin",
        }),
        makeApplication({
          id: APP_B,
          stage: "screening",
          candidate: { id: "c2", name: "Jonas Berg", email: "jonas@example.com", links: {} },
        }),
      ],
      total: 2,
      stage_counts: { new: 1, screening: 1 },
      sources: [],
    });
  });

  it("shows the header, the public URL and the stat tiles for a live job", async () => {
    render(<JobOverviewPage />);
    expect(
      await screen.findByRole("heading", { name: "Senior Frontend Engineer" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("published").length).toBeGreaterThan(0);
    expect(await screen.findByText("Live since Jul 10 · 12 days open")).toBeInTheDocument();
    const urlCard = screen
      .getByRole("button", { name: "Copy job URL" })
      .closest<HTMLElement>("div.card")!;
    expect(
      within(urlCard).getByText(/\/c\/acme\/jobs\/senior-frontend-engineer$/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      `/admin/jobs/${JOB_ID}/edit`,
    );

    const applicationsTile = screen.getByText("Applications · 30d").closest("div")!;
    expect(within(applicationsTile).getByText("3")).toBeInTheDocument();
    expect(within(applicationsTile).getByText("5 all time · +2 new")).toBeInTheDocument();
    const quizTile = screen.getByText("Quiz completion").closest("div")!;
    expect(within(quizTile).getByText("67%")).toBeInTheDocument();
    expect(within(quizTile).getByText("2 of 3 started · median 75%")).toBeInTheDocument();
    const viewsTile = screen.getByText("Views · 30d").closest("div")!;
    expect(within(viewsTile).getByText("1,204")).toBeInTheDocument();
    expect(within(viewsTile).getByText("3,410 all time · not unique")).toBeInTheDocument();
    expect(viewsTile).toHaveAttribute("title", expect.stringMatching(/^Page loads by people\./));
    const rateTile = screen.getByText("Apply rate · 30d").closest("div")!;
    expect(within(rateTile).getByText("0%")).toBeInTheDocument();
    expect(within(rateTile).getByText("3 applications / 1,204 views")).toBeInTheDocument();
    expect(screen.queryByText("Days open")).not.toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /^Views and applications, last 30 days: / }),
    ).toHaveAccessibleName(
      "Views and applications, last 30 days: 435 views and 3 applications, Jul 1 to Jul 30.",
    );
    expect(screen.getByText("quiz preview")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/visitor/i);
  });

  it("counts the same UTC days in the Applications tile and the chart", async () => {
    render(<JobOverviewPage />);
    const applicationsTile = (await screen.findByText("Applications · 30d")).closest("div")!;
    expect(applicationsTile).toHaveAttribute(
      "title",
      "Applications received today and the 29 days before it (UTC), the same days as the chart.",
    );
    const chart = screen.getByRole("img", { name: /^Views and applications, last 30 days/ });
    const charted = Array.from(chart.querySelectorAll<HTMLElement>("[title]")).reduce(
      (sum, bar) => sum + Number(/, (\d+) applications?$/.exec(bar.title)?.[1] ?? 0),
      0,
    );
    expect(charted).toBe(3);
    expect(within(applicationsTile).getByText(String(charted))).toBeInTheDocument();
    for (const label of ["Views · 30d", "Apply rate · 30d"]) {
      expect(screen.getByText(label).closest("div")).toHaveAttribute(
        "title",
        expect.stringMatching(/Today and the 29 days before it \(UTC\)\.$/),
      );
    }
  });

  it("stacks the rail as Share, Status, Assessment, Sources", async () => {
    render(<JobOverviewPage />);
    const share = await screen.findByText("Share this job");
    const rail = share.closest("div.card")!.parentElement!;
    const headings = within(rail)
      .getAllByText(/^(Share this job|Status|Assessment|Sources)$/)
      .map((node) => node.textContent);
    expect(headings).toEqual(["Share this job", "Status", "Assessment", "Sources"]);
  });

  it("offers tracked share links on a live job and asks a draft to publish first", async () => {
    render(<JobOverviewPage />);
    const card = (await screen.findByText("Share this job")).closest("div")!;
    const linkedinRow = (await within(card).findByText("LinkedIn")).closest("li")!;
    expect(
      within(linkedinRow).getByText(/\/c\/acme\/jobs\/senior-frontend-engineer$/),
    ).toBeInTheDocument();
    expect(within(linkedinRow).getByText("?src=linkedin")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Copy LinkedIn link" })).toBeInTheDocument();
    cleanup();
    mockedJobs.get.mockResolvedValue(makeJob({ status: "draft", published_at: null }));
    render(<JobOverviewPage />);
    const draftCard = (await screen.findByText("Share this job")).closest("div")!;
    expect(within(draftCard).getByText("Publish to get share links.")).toBeInTheDocument();
  });

  it("hides the apply rate under 20 views and shows it from there", async () => {
    mockedJobs.stats.mockResolvedValue(
      makeStats({ views: { total: 19, last_30_days: 19 }, last_30_days: 5 }),
    );
    render(<JobOverviewPage />);
    const rateTile = (await screen.findByText("Apply rate · 30d")).closest("div")!;
    expect(within(rateTile).getByText("n/a")).toBeInTheDocument();
    expect(within(rateTile).getByText("under 20 views")).toBeInTheDocument();
    cleanup();
    // a job older than the counter: applications without matching views
    mockedJobs.stats.mockResolvedValue(
      makeStats({ views: { total: 25, last_30_days: 25 }, last_30_days: 40 }),
    );
    render(<JobOverviewPage />);
    const legacy = (await screen.findByText("Apply rate · 30d")).closest("div")!;
    expect(await within(legacy).findByText("n/a")).toBeInTheDocument();
    expect(within(legacy).getByText("applications outnumber counted views")).toBeInTheDocument();
    cleanup();
    mockedJobs.stats.mockResolvedValue(
      makeStats({ views: { total: 100, last_30_days: 100 }, last_30_days: 10 }),
    );
    render(<JobOverviewPage />);
    const shown = (await screen.findByText("Apply rate · 30d")).closest("div")!;
    expect(await within(shown).findByText("10%")).toBeInTheDocument();
  });

  it("explains the draft state: no public link, empty tiles, no candidates", async () => {
    mockedJobs.get.mockResolvedValue(makeJob({ status: "draft", published_at: null }));
    mockedJobs.stats.mockResolvedValue(
      makeStats({
        applications: { total: 0, new: 0, last_7_days: 0 },
        last_30_days: 0,
        by_stage: {},
        by_source: {},
        quiz: {
          attempts_total: 0,
          attempts_started: 0,
          attempts_completed: 0,
          completion_rate: null,
          avg_score: null,
          median_score: null,
          avg_duration_seconds: null,
          score_distribution: Array(10).fill(0),
        },
        days_open: null,
      }),
    );
    mockedApplications.list.mockResolvedValue({
      items: [],
      total: 0,
      stage_counts: {},
      sources: [],
    });
    render(<JobOverviewPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(await screen.findByText("Draft, not published")).toBeInTheDocument();
    expect(screen.getByText("Publish to get a public link")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy job URL" })).not.toBeInTheDocument();
    const viewsTile = screen.getByText("Views · 30d").closest("div")!;
    expect(within(viewsTile).getByText("-")).toBeInTheDocument();
    expect(within(viewsTile).getByText("Publish to start counting")).toBeInTheDocument();
    const rateTile = screen.getByText("Apply rate · 30d").closest("div")!;
    expect(within(rateTile).getByText("-")).toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: /^Views and applications, last 30 days/ }),
    ).not.toBeInTheDocument();
    const applicationsTile = screen.getByText("Applications · 30d").closest("div")!;
    expect(within(applicationsTile).getByText("-")).toBeInTheDocument();
    expect(within(applicationsTile).getByText("Publish to start counting")).toBeInTheDocument();
    const quizTile = screen.getByText("Quiz completion").closest("div")!;
    expect(within(quizTile).getByText("-")).toBeInTheDocument();
    expect(within(quizTile).queryByText("no attempts yet")).not.toBeInTheDocument();
    expect(await screen.findByText("No candidates yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();
  });

  it("never claims a live job went live today while stats are missing", async () => {
    mockedJobs.stats.mockRejectedValue(new Error("boom"));
    render(<JobOverviewPage />);
    expect((await screen.findAllByText("Live since Jul 10")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/today/)).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Marta Vidal" })).toBeInTheDocument();
  });

  it("says when the assessment is off and when a closed job closed", async () => {
    mockedJobs.get.mockResolvedValue(
      makeJob({
        status: "closed",
        closed_at: "2026-08-20T00:00:00Z",
        quiz_config: { ...makeJob().quiz_config, enabled: false },
      }),
    );
    mockedJobs.stats.mockResolvedValue(
      makeStats({
        quiz: { ...makeStats().quiz, attempts_total: 0, attempts_started: 0, attempts_completed: 0, completion_rate: null, median_score: null },
        days_open: 41,
      }),
    );
    render(<JobOverviewPage />);
    expect(await screen.findByText("Closed after 41 days")).toBeInTheDocument();
    const quizTile = screen.getByText("Quiz completion").closest("div")!;
    expect(within(quizTile).getByText("assessment off")).toBeInTheDocument();
  });

  it("lists candidates with stage, score, flags and source, linking into the review", async () => {
    render(<JobOverviewPage />);
    const marta = await screen.findByRole("link", { name: "Marta Vidal" });
    expect(marta).toHaveAttribute("href", `/admin/applicants?job=${JOB_ID}&selected=${APP_A}`);
    const martaRow = marta.closest("tr")!;
    expect(within(martaRow).getByText("75")).toBeInTheDocument();
    expect(within(martaRow).getByText("new")).toBeInTheDocument();
    expect(within(martaRow).getByText("linkedin")).toBeInTheDocument();
    expect(within(martaRow).getByLabelText("1 integrity flag")).toBeInTheDocument();

    const jonasRow = screen.getByRole("link", { name: "Jonas Berg" }).closest("tr")!;
    expect(within(jonasRow).getByText("screening")).toBeInTheDocument();
    expect(within(jonasRow).queryByText("75")).not.toBeInTheDocument();
    expect(within(jonasRow).getAllByText("-")).toHaveLength(2);
    expect(within(jonasRow).queryByText("\u2014")).not.toBeInTheDocument();

    expect(screen.getByRole("link", { name: "All 5 candidates" })).toHaveAttribute(
      "href",
      `/admin/applicants?job=${JOB_ID}`,
    );
    expect(mockedApplications.list).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: JOB_ID, limit: 50 }),
    );
  });

  it("filters the candidate table by stage pill", async () => {
    render(<JobOverviewPage />);
    await screen.findByRole("link", { name: "Marta Vidal" });
    await userEvent.click(screen.getByRole("button", { name: "Screening · 1" }));
    expect(mockedApplications.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ job_id: JOB_ID, stage: "screening" }),
    );
    expect(screen.getByRole("button", { name: "Screening · 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("lists sources with views, applications and apply rate, most viewed first", async () => {
    render(<JobOverviewPage />);
    const card = (await screen.findByText("Sources")).closest("div")!;
    const table = within(card).getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Views" })).toHaveAttribute(
      "title",
      expect.stringMatching(/^Page loads by people\./),
    );
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual(["linkedin4038%", "direct02-"]);
    // a ref: row under 5 views with no application is advisory noise (JP8)
    expect(within(card).queryByText("ref:tiny.example")).not.toBeInTheDocument();
  });

  function noViews(overrides: Partial<JobStats> = {}): JobStats {
    return makeStats({
      views: { total: 0, last_30_days: 0 },
      views_by_source: {},
      daily: makeStats().daily.map((point) => ({ ...point, views: 0 })),
      ...overrides,
    });
  }

  function chartCard(): HTMLElement {
    return screen
      .getByRole("img", { name: /^Views and applications, last 30 days/ })
      .closest<HTMLElement>("div.card")!;
  }

  it("asks a live job with no views to share it, with the preset links right there", async () => {
    mockedJobs.stats.mockResolvedValue(
      noViews({
        applications: { total: 0, new: 0, last_7_days: 0 },
        last_30_days: 0,
        by_source: {},
        daily: makeStats().daily.map((point) => ({ ...point, views: 0, applications: 0 })),
      }),
    );
    render(<JobOverviewPage />);
    const card = (await screen.findByText("No views yet. Share it:")).closest<HTMLElement>("div.card")!;
    expect(card).toBe(chartCard());
    expect(await within(card).findByRole("button", { name: "Copy LinkedIn link" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Copy Newsletter link" })).toBeInTheDocument();
    expect(within(card).getByText(/src=linkedin$/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/visitor/i);
    expect(document.body.textContent).not.toMatch(/[\u2013\u2014]/);
  });

  it("stays neutral on a closed job with no views: nothing to share, no Copy button", async () => {
    mockedJobs.get.mockResolvedValue(makeJob({ status: "closed", closed_at: "2026-08-20T00:00:00Z" }));
    mockedJobs.stats.mockResolvedValue(noViews({ by_source: {}, days_open: 41 }));
    render(<JobOverviewPage />);
    expect(await screen.findByText("No views were counted.")).toBeInTheDocument();
    await screen.findByText("Closed after 41 days");
    expect(screen.queryByText(/Share it/)).not.toBeInTheDocument();
    // the status card's preview-link Copy stays (a closed job is no longer public);
    // no share link is offered anywhere
    expect(
      screen.queryAllByRole("button", { name: /^Copy (LinkedIn|Indeed|X|Newsletter|custom) link$/ }),
    ).toHaveLength(0);
    const sources = screen.getByText("Sources").closest("div")!;
    expect(within(sources).getByText("No views or applications were counted.")).toBeInTheDocument();
  });

  it("explains the counter's start on a job whose applications predate it", async () => {
    mockedJobs.stats.mockResolvedValue(noViews());
    render(<JobOverviewPage />);
    const line = await screen.findByText(/^No views counted yet\. .*counted from the 0\.4\.0 update/);
    expect(line.closest("div.card")).toBe(chartCard());
    expect(within(chartCard()).queryByText(/Share it/)).not.toBeInTheDocument();
    expect(within(chartCard()).queryByRole("button", { name: /^Copy/ })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/[\u2013\u2014]/);
  });

  it("says when nothing was viewed or applied for yet", async () => {
    mockedJobs.stats.mockResolvedValue(makeStats({ by_source: {}, views_by_source: {} }));
    render(<JobOverviewPage />);
    const card = (await screen.findByText("Sources")).closest("div")!;
    expect(within(card).getByText("No views or applications yet.")).toBeInTheDocument();
  });

  it("says why share links are missing when the company summary fails, instead of a skeleton", async () => {
    mockedCompany.summary.mockRejectedValue(new Error("network"));
    render(<JobOverviewPage />);
    expect(await screen.findByText("Public link loads with the company")).toBeInTheDocument();
    expect(await screen.findByText("Share links load with the company.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading share links")).not.toBeInTheDocument();
  });

  it("says the same under the chart when a job with no views cannot build its links", async () => {
    mockedCompany.summary.mockRejectedValue(new Error("network"));
    mockedJobs.stats.mockResolvedValue(
      noViews({
        applications: { total: 0, new: 0, last_7_days: 0 },
        last_30_days: 0,
        by_source: {},
        daily: makeStats().daily.map((point) => ({ ...point, views: 0, applications: 0 })),
      }),
    );
    render(<JobOverviewPage />);
    const card = (await screen.findByText("No views yet. Share it:")).closest<HTMLElement>("div.card")!;
    expect(await within(card).findByText("Share links load with the company.")).toBeInTheDocument();
    expect(within(card).queryByLabelText("Loading share links")).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /^Copy/ })).not.toBeInTheDocument();
  });

  it("passes axe on a live job with every card filled", async () => {
    const { container } = render(<JobOverviewPage />);
    await screen.findByRole("link", { name: "Marta Vidal" });
    await screen.findByRole("button", { name: "Copy LinkedIn link" });
    const results = await axe.run(container, {
      // jsdom has no layout engine: contrast needs real rendering (CI e2e territory)
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
  });

  it("shows a skeleton, not an empty claim, while stats load", async () => {
    mockedJobs.stats.mockReturnValue(new Promise(() => {}));
    render(<JobOverviewPage />);
    const card = (await screen.findByText("Sources")).closest("div")!;
    expect(within(card).getByLabelText("Loading sources")).toHaveAttribute("aria-busy", "true");
    expect(within(card).queryByText(/No views/)).not.toBeInTheDocument();
  });

  it("offers View as candidate as a plain link on a live job", async () => {
    render(<JobOverviewPage />);
    const view = await screen.findByRole("link", { name: "View as candidate" });
    expect(view).toHaveAttribute("href", expect.stringMatching(/\/c\/acme\/jobs\/senior-frontend-engineer$/));
    expect(view).toHaveAttribute("target", "_blank");
    expect(mockedJobs.previewLink).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Copy preview link" })).not.toBeInTheDocument();
  });

  it("fetches a preview link for a draft and opens it as the candidate view", async () => {
    mockedJobs.get.mockResolvedValue(makeJob({ status: "draft", published_at: null }));
    mockedJobs.previewLink.mockResolvedValue({
      url: "http://localhost:3000/c/acme/jobs/senior-frontend-engineer?preview=tok",
      expires_at: "2026-11-02T00:00:00Z",
    });
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<JobOverviewPage />);
    // the Copy button appears once the preview link has been fetched
    expect(await screen.findByRole("button", { name: "Copy preview link" })).toBeInTheDocument();
    expect(mockedJobs.previewLink).toHaveBeenCalledWith(JOB_ID);
    expect(screen.getByText("link valid 7 days")).toBeInTheDocument();
    const view = screen.getByRole("button", { name: "View as candidate" });
    expect(view).toBeEnabled();
    await userEvent.click(view);
    expect(open).toHaveBeenCalledWith(
      "http://localhost:3000/c/acme/jobs/senior-frontend-engineer?preview=tok",
      "_blank",
      "noopener",
    );
    open.mockRestore();
  });

  it("reloads the job and its stats after closing from the status card", async () => {
    mockedJobs.close.mockResolvedValue(makeJob({ status: "closed" }));
    render(<JobOverviewPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    mockedJobs.get.mockResolvedValue(makeJob({ status: "closed", closed_at: "2026-07-22T00:00:00Z" }));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(mockedJobs.close).toHaveBeenCalledWith(JOB_ID);
    expect(await screen.findByRole("button", { name: "Publish" })).toBeInTheDocument();
    expect(mockedJobs.get).toHaveBeenCalledTimes(2);
    expect(mockedJobs.stats).toHaveBeenCalledTimes(2);
  });
});
