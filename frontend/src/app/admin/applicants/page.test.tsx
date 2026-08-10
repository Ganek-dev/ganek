import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  applications,
  notes,
  type ApplicationOut,
  type ApplicationStage,
  type QuizAnswerReview,
} from "@/lib/api";

import ApplicantsPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, jobs: { ...original.api.jobs, list: vi.fn() }, me: vi.fn() },
    applications: {
      list: vi.fn(),
      setStage: vi.fn(),
      cvUrl: vi.fn(),
      quizAnswers: vi.fn(),
      remind: vi.fn(),
      bulkReject: vi.fn(),
    },
    notes: { list: vi.fn(), add: vi.fn(), remove: vi.fn() },
  };
});

const mockedApps = vi.mocked(applications);
const mockedJobs = vi.mocked(api.jobs);
const mockedApi = vi.mocked(api);
const mockedNotes = vi.mocked(notes);

const RECENT = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
const OLDER = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();

function makeApp(overrides: Partial<ApplicationOut>): ApplicationOut {
  return {
    id: "app-1",
    job_id: "job-1",
    candidate: {
      id: "cand-1",
      name: "Jane Applicant",
      email: "jane@example.com",
      links: { github: "https://github.com/jane" },
    },
    cv_filename: "jane.pdf",
    cv_size: 250_000,
    message: "Hello!",
    stage: "new",
    source: null,
    quiz_attempt: {
      status: "completed",
      score: 0.75,
      per_tag_scores: { python: { correct: 3, total: 4 } },
      completed_at: "2026-07-22T10:05:00Z",
      question_ids: ["q1", "q2", "q3", "q4"],
      integrity: {
        blur_count: 2,
        flags: [
          {
            code: "tab_hidden",
            summary: "left the tab 2x (~20s)",
            detail: "The quiz tab was hidden 2 time(s) for about 20s total.",
            question_ids: ["py-gil-1"],
          },
        ],
      },
    },
    created_at: RECENT,
    ...overrides,
  };
}

const ANSWERS: QuizAnswerReview[] = [
  {
    question_id: "q1",
    prompt_md: "What does box-sizing: border-box do?",
    options: { a: "Include padding", b: "Ignore padding", c: "Wraps", d: "Nothing" },
    correct_key: "a",
    explanation_md: "",
    tags: ["css"],
    answer_key: "a",
    is_correct: true,
    response_ms: 11_000,
    integrity_events: [],
  },
  {
    question_id: "q2",
    prompt_md: "Which hook memoizes a value?",
    options: { a: "useMemo", b: "useState", c: "useRef", d: "useEffect" },
    correct_key: "a",
    explanation_md: "",
    tags: ["react"],
    answer_key: "b",
    is_correct: false,
    response_ms: 4_200,
    integrity_events: [{ type: "blur", duration_ms: 12_000 }],
  },
  {
    question_id: "q3",
    prompt_md: "Correct one",
    options: { a: "Yes", b: "No", c: "?", d: "!" },
    correct_key: "a",
    explanation_md: "",
    tags: ["misc"],
    answer_key: "a",
    is_correct: true,
    response_ms: 5_000,
    integrity_events: [],
  },
  {
    question_id: "q4",
    prompt_md: "Timed-out question",
    options: { a: "A", b: "B", c: "C", d: "D" },
    correct_key: "a",
    explanation_md: "",
    tags: ["misc"],
    answer_key: null,
    is_correct: false,
    response_ms: null,
    integrity_events: [],
  },
];

describe("ApplicantsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApps.list.mockResolvedValue([
      makeApp({ id: "app-1", stage: "new" }),
      makeApp({
        id: "app-2",
        stage: "screening",
        created_at: OLDER,
        candidate: {
          id: "cand-2",
          name: "Kenji Sato",
          email: "kenji@example.com",
          links: {},
        },
        quiz_attempt: {
          status: "completed",
          score: 0.35,
          per_tag_scores: {},
          completed_at: null,
          question_ids: ["q1", "q2", "q3", "q4"],
          integrity: { flags: [] },
        },
      }),
    ]);
    mockedApps.setStage.mockImplementation(async (id, stage) =>
      makeApp({ id, stage: stage as ApplicationStage }),
    );
    mockedApps.cvUrl.mockResolvedValue({ download_url: "http://minio.test/cv" });
    mockedApps.quizAnswers.mockResolvedValue(ANSWERS);
    mockedApps.bulkReject.mockResolvedValue({ rejected: 2, skipped: 0 });
    mockedJobs.list.mockResolvedValue([
      { id: "job-1", title: "Backend Engineer" } as never,
    ]);
    mockedApi.me.mockResolvedValue({
      id: "u-1",
      company_id: "co-1",
      email: "recruiter@acme.dev",
      role: "admin",
      has_password: true,
    });
    mockedNotes.list.mockResolvedValue([]);
    mockedNotes.add.mockResolvedValue({
      id: "note-1",
      body: "",
      author_email: "recruiter@acme.dev",
      created_at: RECENT,
    });
    mockedNotes.remove.mockResolvedValue(undefined);
  });

  it("renders the list with score chips, flag dot and stage-pill counts", async () => {
    render(<ApplicantsPage />);
    const janeButton = (await screen.findByRole("button", { name: /Jane Applicant/ }))!;
    expect(within(janeButton).getByText("75")).toBeInTheDocument();
    expect(within(janeButton).getByLabelText("integrity flag")).toBeInTheDocument();
    expect(within(janeButton).getByText(/applied .* · new/)).toBeInTheDocument();

    const kenjiButton = screen.getByRole("button", { name: /Kenji Sato/ });
    expect(within(kenjiButton).getByText("35")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: /^All · 2/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^New · 1/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Screening · 1/ })).toBeInTheDocument();
  });

  it("selecting an applicant loads answers and renders per-question rows", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await waitFor(() => expect(mockedApps.quizAnswers).toHaveBeenCalledWith("app-1"));

    const wrongRow = (
      await screen.findByText("Which hook memoizes a value?")
    ).closest("li")!;
    expect(within(wrongRow).getByText("useMemo")).toBeInTheDocument();
    expect(within(wrongRow).getByText("useState")).toBeInTheDocument();
    expect(within(wrongRow).getByText("left the tab 12.0s")).toBeInTheDocument();
    // timed-out row
    expect(screen.getByText("time ran out — no answer")).toBeInTheDocument();
    // score strip totals
    expect(screen.getByLabelText(/2 correct, 1 wrong, 1 timed out/)).toBeInTheDocument();
    // integrity card summary pill
    expect(screen.getByText("1 flag")).toBeInTheDocument();
  });

  it("Advance advances to the next stage, Reject sets rejected", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "screening", false),
    );

    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "rejected", false),
    );
  });

  it("Send reminder appears for pending attempts and calls the endpoint", async () => {
    mockedApps.list.mockResolvedValue([
      makeApp({
        quiz_attempt: {
          status: "pending",
          score: null,
          per_tag_scores: {},
          completed_at: null,
          question_ids: ["q1", "q2"],
          integrity: { blur_count: 0, flags: [] },
        },
      }),
    ]);
    mockedApps.remind.mockResolvedValue({ sent: true });
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await userEvent.click(screen.getByRole("button", { name: /send reminder/i }));
    await waitFor(() => expect(mockedApps.remind).toHaveBeenCalledWith("app-1"));
    expect(await screen.findByText(/reminder sent/i)).toBeInTheDocument();
  });

  it("Send reminder is absent for completed attempts", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(screen.queryByRole("button", { name: /send reminder/i })).not.toBeInTheDocument();
  });

  it("Email-the-candidate checkbox passes notify through stage changes", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "rejected", true),
    );
  });

  it("withdrawn applications get a chip, a count and a filter", async () => {
    mockedApps.list.mockResolvedValue([makeApp({ stage: "withdrawn" })]);
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(screen.getByRole("button", { name: /^Withdrawn · 1/ })).toBeInTheDocument();
    // the recruiter stage select never offers withdrawn (candidate-only)
    expect(screen.queryByRole("option", { name: /withdrawn/i })).not.toBeInTheDocument();
    // and a withdrawn application offers no Advance/Reject actions
    expect(screen.queryByRole("button", { name: "Advance" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("stage-pill filter narrows the list and shows the empty state", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    mockedApps.list.mockResolvedValueOnce([]);
    await userEvent.click(screen.getByRole("button", { name: /^Rejected · 0/ }));
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ stage: "rejected" }),
      ),
    );
    expect(await screen.findByText("No applications match.")).toBeInTheDocument();
  });

  it("opens the CV in a new tab from the detail panel", async () => {
    const spy = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await userEvent.click(screen.getByRole("button", { name: /jane\.pdf/ }));
    expect(mockedApps.cvUrl).toHaveBeenCalledWith("app-1");
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("http://minio.test/cv", "_blank", "noopener"),
    );
    spy.mockRestore();
  });

  it("shows the action bar when rows are checked", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    expect(await screen.findByText("1 selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: /select kenji sato/i }));
    expect(await screen.findByText("2 selected")).toBeInTheDocument();
  });

  it("checking a row does not open its detail panel", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await userEvent.click(screen.getByRole("checkbox", { name: /select kenji sato/i }));
    expect(screen.getByRole("heading", { name: "Jane Applicant" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Kenji Sato" })).not.toBeInTheDocument();
  });

  it("two-step confirms and calls bulkReject with the ids and email toggle", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /select kenji sato/i }));

    await userEvent.click(screen.getByRole("checkbox", { name: /also email candidates/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    expect(await screen.findByText("Reject 2 applicants?")).toBeInTheDocument();

    mockedApps.list.mockResolvedValueOnce([]);
    await userEvent.click(screen.getByRole("button", { name: "Yes, reject" }));

    await waitFor(() =>
      expect(mockedApps.bulkReject).toHaveBeenCalledWith(["app-1", "app-2"], true),
    );
    await waitFor(() => expect(mockedApps.list).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Rejected 2")).toBeInTheDocument();
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
  });

  it("Keep them cancels the confirm step without calling bulkReject", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    expect(await screen.findByText("Reject 1 applicants?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Keep them" }));
    expect(screen.queryByText(/Reject 1 applicants\?/)).not.toBeInTheDocument();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(mockedApps.bulkReject).not.toHaveBeenCalled();
  });

  it("clears selection on job-filter change but keeps it across stage pills", async () => {
    mockedJobs.list.mockResolvedValue([
      { id: "job-1", title: "Backend Engineer" } as never,
      { id: "job-2", title: "Frontend Engineer" } as never,
    ]);
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    expect(await screen.findByText("1 selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^New · 1/ }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Filter by job"), "job-2");
    await waitFor(() => expect(screen.queryByText(/selected/)).not.toBeInTheDocument());
  });

  it("shows the selected candidates' names at confirm time even after their rows are filtered out by a different stage pill", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /select kenji sato/i }));
    expect(await screen.findByText("2 selected")).toBeInTheDocument();

    mockedApps.list.mockResolvedValueOnce([]);
    await userEvent.click(screen.getByRole("button", { name: /^Rejected · 0/ }));
    await waitFor(() => expect(screen.getByText("No applications match.")).toBeInTheDocument());

    // both rows are gone from the list, but the bar (and its selection)
    // survives the refetch, so the confirm step must still say who is
    // affected.
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    expect(await screen.findByText("Reject 2 applicants?")).toBeInTheDocument();
    expect(screen.getByText("Jane Applicant, Kenji Sato")).toBeInTheDocument();
  });

  it("Clear empties the selection and hides the bar", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    expect(await screen.findByText("1 selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: /select jane applicant/i }),
    ).not.toBeChecked();
  });
});
