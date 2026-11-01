import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  ApiError,
  applications,
  notes,
  scorecards,
  type ApplicationOut,
  type ApplicationStage,
  type EmailDelivery,
  type QuizAnswerReview,
  emailTemplates,
  type EmailKindInfo,
} from "@/lib/api";

import ApplicantsPage from "./page";

let search = new URLSearchParams();
const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/applicants",
  useRouter: () => ({ push: vi.fn(), replace }),
  useSearchParams: () => search,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, jobs: { ...original.api.jobs, list: vi.fn() }, me: vi.fn() },
    applications: {
      ...original.applications, // exportUrl stays real: it only builds a href
      list: vi.fn(),
      get: vi.fn(),
      setStage: vi.fn(),
      cvUrl: vi.fn(),
      quizAnswers: vi.fn(),
      timeline: vi.fn(),
      emails: vi.fn(),
      accessLog: vi.fn(),
      remind: vi.fn(),
      emailPreview: vi.fn(),
      sendMessage: vi.fn(),
      messagePreview: vi.fn(),
      bulkReject: vi.fn(),
      bulkStage: vi.fn(),
      eraseCandidate: vi.fn(),
      dsarExport: vi.fn(),
      updateCandidateEmail: vi.fn(),
    },
    notes: { list: vi.fn(), add: vi.fn(), remove: vi.fn() },
    scorecards: { list: vi.fn().mockResolvedValue([]) },
    emailTemplates: { ...original.emailTemplates, list: vi.fn() },
  };
});

const mockedApps = vi.mocked(applications);
const mockedJobs = vi.mocked(api.jobs);
const mockedApi = vi.mocked(api);
const mockedNotes = vi.mocked(notes);
const mockedScorecards = vi.mocked(scorecards);
const mockedTemplates = vi.mocked(emailTemplates);

function templateKinds(): { kinds: EmailKindInfo[] } {
  const base = { placeholders: [], builtin: { subject: "s", body: "b" }, templates: [] };
  const row = (id: string, kind: EmailKindInfo["kind"], name: string, is_default: boolean) => ({
    id,
    kind,
    name,
    subject: "s",
    body: "b",
    is_default,
    created_at: "",
    updated_at: "",
  });
  return {
    kinds: [
      { kind: "quiz_invite", label: "Assessment invite", ...base },
      { kind: "quiz_reminder", label: "Assessment reminder", ...base },
      { kind: "stage_advance", label: "Interview", ...base, templates: [row("t-u", "stage_advance", "U", true)] },
      { kind: "rejection", label: "Rejection", ...base, templates: [row("t-a", "rejection", "A", true)] },
    ],
  };
}

const RECENT = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
const OLDER = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();

function makeDelivery(overrides: Partial<EmailDelivery>): EmailDelivery {
  return {
    id: "mail-1",
    kind: "rejection",
    status: "sent",
    attempts: 1,
    last_error: null,
    created_at: RECENT,
    sent_at: RECENT,
    send_after: null,
    cancelled_at: null,
    subject: null,
    text: null,
    ...overrides,
  };
}

function makeApp(overrides: Partial<ApplicationOut>): ApplicationOut {
  return {
    screening_answers: [],
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
    stage_changed_at: RECENT, // same instant as created_at: untouched row
    rejection_reason: null,
    rejection_note: null,
    quiz_attempt: {
      status: "completed",
      score: 0.75,
      per_tag_scores: { python: { correct: 3, total: 4 } },
      completed_at: "2026-07-22T10:05:00Z",
      question_ids: ["q1", "q2", "q3", "q4"],
      time_multiplier: 1,
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


function pageOf(items: ApplicationOut[]) {
  const stage_counts: Partial<Record<ApplicationStage, number>> = {};
  for (const app of items) stage_counts[app.stage] = (stage_counts[app.stage] ?? 0) + 1;
  return { items, total: items.length, stage_counts, sources: ["direct", "linkedin"] };
}

describe("ApplicantsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams();
    mockedApps.list.mockResolvedValue(pageOf([
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
          time_multiplier: 1,
          integrity: { flags: [] },
        },
      }),
    ]));
    mockedApps.setStage.mockImplementation(async (id, stage) =>
      makeApp({ id, stage: stage as ApplicationStage }),
    );
    mockedApps.cvUrl.mockResolvedValue({ download_url: "http://minio.test/cv" });
    mockedApps.quizAnswers.mockResolvedValue(ANSWERS);
    mockedApps.bulkReject.mockResolvedValue({ rejected: 2, skipped: 0 });
    mockedTemplates.list.mockResolvedValue(templateKinds());
    mockedApps.emailPreview.mockResolvedValue({
      kind: "rejection",
      subject: "Your application to ACME Ganek",
      text: "Thank you, Jane Applicant",
      html: "",
      body: "Thank you, Jane Applicant",
    });
    mockedApps.bulkStage.mockResolvedValue({ updated: 2, skipped: 0 });
    mockedApps.eraseCandidate.mockResolvedValue({ applications: 2, google_event_failures: 0 });
    mockedApps.dsarExport.mockResolvedValue({ candidate: { email: "jane@example.com" } });
    mockedApps.updateCandidateEmail.mockResolvedValue(makeApp({ id: "app-1" }));
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
    mockedScorecards.list.mockResolvedValue([]);
    mockedApps.timeline.mockResolvedValue([]);
    mockedApps.emails.mockResolvedValue([]);
    mockedApps.accessLog.mockResolvedValue([]);
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

  it("pre-filters by the job named in ?job=", async () => {
    search = new URLSearchParams("job=job-2");
    mockedJobs.list.mockResolvedValue([
      { id: "job-1", title: "Backend Engineer" } as never,
      { id: "job-2", title: "Data Engineer" } as never,
    ]);
    render(<ApplicantsPage />);
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenCalledWith(expect.objectContaining({ job_id: "job-2" })),
    );
    await waitFor(() => expect(screen.getByLabelText("Filter by job")).toHaveValue("job-2"));
  });

  it("preselects the applicant named by ?selected= when it is in the list", async () => {
    search = new URLSearchParams("selected=app-2");
    render(<ApplicantsPage />);
    const kenjiButton = await screen.findByRole("button", { name: /Kenji Sato/ });
    expect(kenjiButton).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /Jane Applicant/ })).not.toHaveAttribute(
      "aria-current",
    );
    expect(mockedApps.get).not.toHaveBeenCalled();
  });

  it("fetches and pins an applicant named by ?selected= that is outside the first page", async () => {
    search = new URLSearchParams("selected=app-9");
    mockedApps.get.mockResolvedValue(
      makeApp({
        id: "app-9",
        stage: "screening",
        candidate: { id: "cand-9", name: "Far Away", email: "far@example.com", links: {} },
      }),
    );
    render(<ApplicantsPage />);
    const farButton = await screen.findByRole("button", { name: /Far Away/ });
    expect(farButton).toHaveAttribute("aria-current", "true");
    expect(mockedApps.get).toHaveBeenCalledWith("app-9");
    // the pinned row sits above the page so the reviewer sees why they landed here
    const names = screen
      .getAllByRole("button", { name: /Far Away|Jane Applicant|Kenji Sato/ })
      .map((button) => button.textContent ?? "");
    expect(names[0]).toMatch(/Far Away/);
  });

  it("loads more pages and keeps whole-set pill counts", async () => {
    mockedApps.list
      .mockResolvedValueOnce({
        items: [makeApp({ id: "app-1", stage: "new" })],
        total: 2,
        stage_counts: { new: 2 },
        sources: [],
      })
      .mockResolvedValueOnce({
        items: [
          makeApp({
            id: "app-9",
            stage: "new",
            candidate: { id: "c9", name: "Nils Late", email: "nils@example.com", links: {} },
          }),
        ],
        total: 2,
        stage_counts: { new: 2 },
        sources: [],
      });
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    // pill counts come from the server, not the loaded slice
    expect(screen.getByRole("button", { name: /^All · 2/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more (1 of 2)" }));
    expect(await screen.findByRole("button", { name: /Nils Late/ })).toBeInTheDocument();
    expect(
      mockedApps.list.mock.calls[1][0],
    ).toMatchObject({ offset: 1 });
    expect(screen.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
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
    expect(screen.getByText("time ran out - no answer")).toBeInTheDocument();
    // score strip totals
    expect(screen.getByLabelText(/2 correct, 1 wrong, 1 timed out/)).toBeInTheDocument();
    // integrity card summary pill
    expect(screen.getByText("1 flag")).toBeInTheDocument();
  });

  it("mounts the scorecards card for the selected applicant and opens the form on ?scorecard=1", async () => {
    search = new URLSearchParams("selected=app-2&scorecard=1");
    mockedScorecards.list.mockResolvedValue([
      {
        id: "sc-1",
        application_id: "app-2",
        reviewer_user_id: "u-1",
        reviewer_label: "recruiter",
        requested_by_label: null,
        interview_id: null,
        requested_at: OLDER,
        due_from: OLDER,
        submitted_at: null,
        dismissed_at: null,
        declined_at: null,
        state: "open",
        waiting_days: 1,
        criteria: [{ id: "c1", label: "Communication", hint: "" }],
        ratings: {},
        recommendation: null,
        comment: null,
        edited: false,
        can_edit: false,
      },
    ]);
    render(<ApplicantsPage />);
    expect(await screen.findByRole("radiogroup", { name: "Communication" })).toBeInTheDocument();
    expect(mockedScorecards.list).toHaveBeenCalledWith("app-2");
  });

  it("asks for the timeline of the selected applicant", async () => {
    mockedApps.timeline.mockResolvedValue([
      {
        id: "t1",
        kind: "stage.changed",
        at: RECENT,
        actor_label: "Erika",
        actor_email: "erika@acme.example",
        payload: { from: "new", to: "screening" },
      },
    ]);
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await waitFor(() => expect(mockedApps.timeline).toHaveBeenCalledWith("app-1"));
    const timeline = await screen.findByRole("region", { name: "Timeline" });
    expect(within(timeline).getByText("Erika moved to Screening")).toBeInTheDocument();
  });

  it("refetches the timeline after a stage change from the panel", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await waitFor(() => expect(mockedApps.timeline).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    await waitFor(() => expect(mockedApps.timeline).toHaveBeenCalledTimes(2));
  });

  it("asks for the access trail of the selected applicant", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await waitFor(() => expect(mockedApps.accessLog).toHaveBeenCalledWith("app-1"));
  });

  it("notes a granted extra-time accommodation on the integrity card", async () => {
    const base = makeApp({});
    mockedApps.list.mockResolvedValue(
      pageOf([
        {
          ...base,
          quiz_attempt: {
            ...base.quiz_attempt!,
            time_multiplier: 2,
            integrity: {
              ...base.quiz_attempt!.integrity,
              accommodation: { time_multiplier: 2, by_user_id: "u1", at: RECENT },
            },
          },
        },
      ]),
    );
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(
      await screen.findByText("Extra time granted: 2x the usual limit per question."),
    ).toBeInTheDocument();
  });

  it("Advance advances to the next stage", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "screening", false),
    );
  });

  it("confirms a stage move with a toast whose Undo moves the row back quietly", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    const status = await screen.findByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Moved Jane Applicant to Screening."));
    expect(status).not.toHaveTextContent("Email sent");
    await userEvent.click(within(status).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenLastCalledWith("app-1", "new", false),
    );
    await waitFor(() => expect(status).toHaveTextContent("Moved Jane Applicant back to New."));
  });

  it("the toast stays quiet about email on a move that sends none", async () => {
    // the checkbox is on, but only interview and rejection carry a mail:
    // a move to screening must not claim one went out (QA pass 2026-10-31)
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    const status = await screen.findByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Moved Jane Applicant to Screening."));
    expect(status).not.toHaveTextContent("Email sent");
  });

  it("shows how long the applicant has sat in the current stage", async () => {
    const moved = new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString();
    mockedApps.list.mockResolvedValue(
      pageOf([{ ...makeApp({}), stage: "screening", stage_changed_at: moved }]),
    );
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(screen.getByText(/in screening for 4d/)).toBeInTheDocument();
  });

  it("Send reminder appears for pending attempts and calls the endpoint", async () => {
    mockedApps.list.mockResolvedValue(pageOf([
      makeApp({
        quiz_attempt: {
          status: "pending",
          score: null,
          per_tag_scores: {},
          completed_at: null,
          question_ids: ["q1", "q2"],
          time_multiplier: 1,
          integrity: { blur_count: 0, flags: [] },
        },
      }),
    ]));
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

  it("Email-the-candidate checkbox previews the rejection before sending", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });

    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Your application to ACME Ganek")).toBeInTheDocument();
    expect(mockedApps.setStage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "rejected", true, {
        rejectionReason: null,
        rejectionNote: null,
        templateId: "t-a",
        sendAfter: null,
      }),
    );
    // a rejection with the checkbox on does send one, and the toast says so
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Moved Jane Applicant to Rejected. Email sent.",
      ),
    );
  });

  it("Cancel in the preview keeps the stage", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    await screen.findByText("Your application to ACME Ganek");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByText("Your application to ACME Ganek")).not.toBeInTheDocument(),
    );
    expect(mockedApps.setStage).not.toHaveBeenCalled();
  });

  it("Advance to a stage without an email moves immediately even with the checkbox on", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "screening", true),
    );
    expect(screen.queryByText("Your application to ACME Ganek")).not.toBeInTheDocument();
    expect(mockedApps.emailPreview).not.toHaveBeenCalled();
  });

  it("Reject always opens the dialog; without the checkbox it rejects without an email", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Reject Jane Applicant" });
    expect(within(dialog).getByText("No email will be sent.")).toBeInTheDocument();
    expect(mockedApps.emailPreview).not.toHaveBeenCalled();
    expect(mockedApps.setStage).not.toHaveBeenCalled();
    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: "Reason (internal, optional)" }),
      "Another candidate preferred",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "rejected", false, {
        rejectionReason: "another_candidate",
        rejectionNote: null,
      }),
    );
  });

  it("Cancel in the reject dialog sends nothing", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Reject Jane Applicant" });
    await userEvent.type(within(dialog).getByLabelText("Internal note"), "Not a fit");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Reject Jane Applicant" })).not.toBeInTheDocument(),
    );
    expect(mockedApps.setStage).not.toHaveBeenCalled();
  });

  it("an edited rejection email reaches setStage as subject and body", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Email to Jane Applicant" });
    await within(dialog).findByText("Your application to ACME Ganek");
    await userEvent.click(within(dialog).getByRole("button", { name: "Edit this email" }));
    const subject = within(dialog).getByRole("textbox", { name: "Subject" });
    await userEvent.clear(subject);
    await userEvent.type(subject, "About your application");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reject and send email" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith(
        "app-1",
        "rejected",
        true,
        expect.objectContaining({ subject: "About your application", body: "Thank you, Jane Applicant" }),
      ),
    );
  });

  it("Send a message opens the dialog, sends, toasts and refetches the timeline", async () => {
    mockedApps.sendMessage.mockResolvedValue({ queued: true });
    mockedApps.messagePreview.mockResolvedValue({
      kind: "message",
      subject: "Quick question",
      body: "Hi Jane",
      text: "Hi Jane\n\n- ACME Ganek\n",
      html: "",
    });
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    const timelineCalls = mockedApps.timeline.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Send a message" }));
    const dialog = await screen.findByRole("dialog", { name: "Message to Jane Applicant" });
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Subject" }), "Quick question");
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Body" }), "Hi Jane");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(mockedApps.sendMessage).toHaveBeenCalledWith("app-1", {
        subject: "Quick question",
        body: "Hi Jane",
      }),
    );
    expect(await screen.findByText("Message sent.")).toBeInTheDocument();
    await waitFor(() => expect(mockedApps.timeline.mock.calls.length).toBeGreaterThan(timelineCalls));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Message to Jane Applicant" })).not.toBeInTheDocument(),
    );
  });

  it("Reject with the checkbox sends the reason with the email", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Email to Jane Applicant" });
    await within(dialog).findByText("Your application to ACME Ganek");
    await userEvent.selectOptions(
      within(dialog).getByRole("combobox", { name: "Reason (internal, optional)" }),
      "Skills below the bar",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Reject and send email" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "rejected", true, {
        rejectionReason: "skills_gap",
        rejectionNote: null,
        templateId: "t-a",
        sendAfter: null,
      }),
    );
  });

  it("a rejected row without a rejection mail offers Send rejection email", async () => {
    mockedApps.list.mockResolvedValue(pageOf([makeApp({ stage: "rejected" })]));
    mockedApps.emails.mockResolvedValueOnce([]);
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    const button = await screen.findByRole("button", { name: "Send rejection email" });
    expect(mockedApps.emails).toHaveBeenCalledWith("app-1");

    mockedApps.emails.mockResolvedValue([makeDelivery({ status: "scheduled" })]);
    await userEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Send rejection email to Jane Applicant" });
    await within(dialog).findByText("Your application to ACME Ganek");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send email" }));
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith(
        "app-1",
        "rejected",
        true,
        expect.objectContaining({ sendAfter: null }),
      ),
    );
    // the trail reloads and the button goes away
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Send rejection email" })).not.toBeInTheDocument(),
    );
  });

  it.each(["scheduled", "queued", "sent"])(
    "no Send rejection email while a rejection mail is %s",
    async (status) => {
      mockedApps.list.mockResolvedValue(pageOf([makeApp({ stage: "rejected" })]));
      mockedApps.emails.mockResolvedValue([makeDelivery({ status })]);
      render(<ApplicantsPage />);
      await screen.findByRole("heading", { name: "Jane Applicant" });
      await waitFor(() => expect(mockedApps.emails).toHaveBeenCalled());
      expect(screen.queryByRole("button", { name: "Send rejection email" })).not.toBeInTheDocument();
    },
  );

  it("a cancelled rejection mail brings the button back; other mail kinds do not hide it", async () => {
    mockedApps.list.mockResolvedValue(pageOf([makeApp({ stage: "rejected" })]));
    mockedApps.emails.mockResolvedValue([
      makeDelivery({ id: "m2", status: "cancelled", cancelled_at: RECENT }),
      makeDelivery({ id: "m3", kind: "quiz_invite", status: "sent" }),
    ]);
    render(<ApplicantsPage />);
    expect(await screen.findByRole("button", { name: "Send rejection email" })).toBeInTheDocument();
  });

  it("no Send rejection email when the trail fails to load or the row is not rejected", async () => {
    mockedApps.list.mockResolvedValue(pageOf([makeApp({ stage: "rejected" })]));
    mockedApps.emails.mockRejectedValue(new Error("boom"));
    const { unmount } = render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await waitFor(() => expect(mockedApps.emails).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Send rejection email" })).not.toBeInTheDocument();
    unmount();

    mockedApps.emails.mockClear();
    mockedApps.list.mockResolvedValue(pageOf([makeApp({ stage: "screening" })]));
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(screen.queryByRole("button", { name: "Send rejection email" })).not.toBeInTheDocument();
    expect(mockedApps.emails).not.toHaveBeenCalled();
  });

  it("a 409 from mail-again shows the server detail", async () => {
    mockedApps.list.mockResolvedValue(pageOf([makeApp({ stage: "rejected" })]));
    mockedApps.setStage.mockRejectedValue(new ApiError(409, "A rejection email is already scheduled."));
    render(<ApplicantsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Send rejection email" }));
    const dialog = await screen.findByRole("dialog", { name: "Send rejection email to Jane Applicant" });
    await within(dialog).findByText("Your application to ACME Ganek");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send email" }));
    expect(await screen.findByText("A rejection email is already scheduled.")).toBeInTheDocument();
  });

  it("the toast names the scheduled time after a delayed reject, and undo says it was cancelled", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("checkbox", { name: /email the candidate/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: /Email to Jane Applicant/ });
    await within(dialog).findByText("Your application to ACME Ganek");
    await userEvent.click(within(dialog).getByRole("radio", { name: /Tomorrow morning/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Reject and email tomorrow morning" }));
    const status = await screen.findByRole("status");
    await waitFor(() =>
      expect(status).toHaveTextContent(
        /Moved Jane Applicant to Rejected\. Email scheduled for [A-Z][a-z]{2} (\d{1,2} [A-Z][a-z]{2} )?09:00\./,
      ),
    );
    expect(status).not.toHaveTextContent("Email sent");
    await userEvent.click(within(status).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(status).toHaveTextContent("Moved Jane Applicant back to New. Scheduled email cancelled."),
    );
  });

  it("withdrawn applications get a chip, a count and a filter", async () => {
    mockedApps.list.mockResolvedValue(pageOf([makeApp({ stage: "withdrawn" })]));
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

    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: /^Rejected · 0/ }));
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ stage: "rejected" }),
      ),
    );
    expect(await screen.findByText("No applications match.")).toBeInTheDocument();
  });

  it("shows where the selected applicant came from", async () => {
    mockedApps.list.mockResolvedValue(
      pageOf([makeApp({ id: "app-1", stage: "new", source: "linkedin" })]),
    );
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(screen.getByText(/applied .* · via linkedin$/)).toBeInTheDocument();
  });

  it("says nothing about the source when none was recorded", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(screen.queryByText(/· via /)).not.toBeInTheDocument();
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

    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: "Yes, reject" }));

    await waitFor(() =>
      expect(mockedApps.bulkReject).toHaveBeenCalledWith(["app-1", "app-2"], true, {
        rejectionReason: null,
        rejectionNote: null,
        templateId: "t-a",
        sendAfter: expect.stringMatching(/T09:00:00/),
      }),
    );
    await waitFor(() => expect(mockedApps.list).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Rejected 2")).toBeInTheDocument();
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
  });

  it("bulk reject passes the reason and note", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /select kenji sato/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    expect(await screen.findByText("Reject 2 applicants?")).toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Reason (internal, optional)" }),
      "No response from the candidate",
    );
    await userEvent.type(screen.getByLabelText("Internal note"), " Two reminders, no reply ");
    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: "Yes, reject" }));
    await waitFor(() =>
      expect(mockedApps.bulkReject).toHaveBeenCalledWith(["app-1", "app-2"], false, {
        rejectionReason: "no_response",
        rejectionNote: "Two reminders, no reply",
      }),
    );
  });

  it("Keep them discards a typed reason and note", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    await screen.findByText("Reject 1 applicant?");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Reason (internal, optional)" }),
      "Skills below the bar",
    );
    await userEvent.type(screen.getByLabelText("Internal note"), "About Jane only");
    await userEvent.click(screen.getByRole("button", { name: "Keep them" }));

    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    await screen.findByText("Reject 1 applicant?");
    expect(screen.getByRole("combobox", { name: "Reason (internal, optional)" })).toHaveValue("");
    expect(screen.getByLabelText("Internal note")).toHaveValue("");
  });

  it("bulk bar shows the template selects and a labelled preview per mail kind when emailing", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /select kenji sato/i }));
    expect(screen.queryByRole("combobox", { name: "Rejection template" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /also email candidates/i }));
    const select = await screen.findByRole("combobox", { name: "Rejection template" });
    expect(select).toHaveValue("t-a");
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual([
      "Ganek default",
      "A",
    ]);
    expect(
      await screen.findByText(
        "Rejection email. Shown for Jane Applicant; each candidate gets their own values.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Interview email. Shown for Jane Applicant; each candidate gets their own values.",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "rejection", "t-a"),
    );
    await waitFor(() =>
      expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "stage_advance", "t-u"),
    );
    await userEvent.selectOptions(select, "Ganek default");
    await waitFor(() =>
      expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "rejection", "builtin"),
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    expect(await screen.findByText("Email: Ganek default")).toBeInTheDocument();
    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: "Yes, reject" }));
    await waitFor(() =>
      expect(mockedApps.bulkReject).toHaveBeenCalledWith(["app-1", "app-2"], true, {
        rejectionReason: null,
        rejectionNote: null,
        templateId: "builtin",
        sendAfter: expect.stringMatching(/T09:00:00/),
      }),
    );
  });

  it("bulk reject with email defaults to tomorrow morning and passes send_after", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /also email candidates/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    await screen.findByText("Reject 1 applicant?");
    expect(screen.getByRole("radio", { name: /Tomorrow morning/ })).toBeChecked();
    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: "Yes, reject" }));
    await waitFor(() => expect(mockedApps.bulkReject).toHaveBeenCalled());
    const fields = mockedApps.bulkReject.mock.calls[0][2];
    expect(fields?.sendAfter).toMatch(/T09:00:00/);
  });

  it("send now in the bulk bar passes sendAfter null", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /also email candidates/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    await screen.findByText("Reject 1 applicant?");
    await userEvent.click(screen.getByRole("radio", { name: /Send now/ }));
    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: "Yes, reject" }));
    await waitFor(() => expect(mockedApps.bulkReject).toHaveBeenCalled());
    expect(mockedApps.bulkReject.mock.calls[0][2]).toHaveProperty("sendAfter", null);
  });

  it("the bulk When choice resets to tomorrow each time the confirm step opens, and is absent without email", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    await screen.findByText("Reject 1 applicant?");
    expect(screen.queryByRole("radio", { name: /Send now/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep them" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /also email candidates/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    await userEvent.click(await screen.findByRole("radio", { name: /Send now/ }));
    await userEvent.click(screen.getByRole("button", { name: "Keep them" }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    expect(await screen.findByRole("radio", { name: /Tomorrow morning/ })).toBeChecked();
  });

  it("bulk move to interview carries the stage_advance template", async () => {
    mockedApps.bulkStage.mockResolvedValue({ updated: 2, skipped: 0 });
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByLabelText("Select Jane Applicant"));
    await userEvent.click(screen.getByLabelText("Select Kenji Sato"));
    await userEvent.click(screen.getByLabelText("Also email candidates"));
    const select = await screen.findByRole("combobox", { name: "Interview template" });
    expect(select).toHaveValue("t-u");
    await userEvent.selectOptions(screen.getByLabelText("Move selected to stage"), "interview");
    await waitFor(() =>
      expect(mockedApps.bulkStage).toHaveBeenCalledWith(["app-1", "app-2"], "interview", true, {
        templateId: "t-u",
      }),
    );
  });

  it("Keep them cancels the confirm step without calling bulkReject", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });

    await userEvent.click(screen.getByRole("checkbox", { name: /select jane applicant/i }));
    await userEvent.click(screen.getByRole("button", { name: "Reject…" }));
    expect(await screen.findByText("Reject 1 applicant?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Keep them" }));
    expect(screen.queryByText(/Reject 1 applicant\?/)).not.toBeInTheDocument();
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

    mockedApps.list.mockResolvedValueOnce(pageOf([]));
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

  async function openMoreActions() {
    render(<ApplicantsPage />);
    await screen.findByRole("heading", { name: "Jane Applicant" });
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    return within(await screen.findByRole("menu"));
  }

  it("⋯ menu exports the DSAR bundle as a JSON download", async () => {
    const downloads: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => "blob:mock"),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloads.push(this.download);
      });

    const menu = await openMoreActions();
    await userEvent.click(menu.getByRole("menuitem", { name: "Export data (JSON)" }));

    await waitFor(() => expect(mockedApps.dsarExport).toHaveBeenCalledWith("app-1"));
    await waitFor(() => expect(downloads).toEqual(["dsar-jane@example.com.json"]));
    clickSpy.mockRestore();
  });

  it("erase is two-step: confirm copy first, then the call and a flash", async () => {
    const menu = await openMoreActions();
    await userEvent.click(menu.getByRole("menuitem", { name: "Erase candidate…" }));

    expect(
      await screen.findByText(/Erase Jane Applicant's data\? This permanently removes/),
    ).toBeInTheDocument();
    expect(mockedApps.eraseCandidate).not.toHaveBeenCalled();

    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: "Yes, erase" }));
    await waitFor(() => expect(mockedApps.eraseCandidate).toHaveBeenCalledWith("app-1"));
    expect(await screen.findByText("Candidate data erased")).toBeInTheDocument();
  });

  it("erase flash reports google event failures", async () => {
    mockedApps.eraseCandidate.mockResolvedValue({
      applications: 1,
      google_event_failures: 1,
    });
    const menu = await openMoreActions();
    await userEvent.click(menu.getByRole("menuitem", { name: "Erase candidate…" }));
    mockedApps.list.mockResolvedValueOnce(pageOf([]));
    await userEvent.click(screen.getByRole("button", { name: "Yes, erase" }));
    expect(
      await screen.findByText(
        "Candidate data erased - 1 calendar event(s) could not be removed",
      ),
    ).toBeInTheDocument();
  });

  it("Keep cancels the erase confirm without calling the endpoint", async () => {
    const menu = await openMoreActions();
    await userEvent.click(menu.getByRole("menuitem", { name: "Erase candidate…" }));
    await userEvent.click(await screen.findByRole("button", { name: "Keep" }));
    expect(mockedApps.eraseCandidate).not.toHaveBeenCalled();
    expect(screen.queryByText(/permanently removes/)).not.toBeInTheDocument();
  });

  it("edit-email dialog saves the corrected address", async () => {
    const menu = await openMoreActions();
    await userEvent.click(menu.getByRole("menuitem", { name: "Edit candidate email…" }));

    const input = await screen.findByLabelText("Candidate email");
    expect(input).toHaveValue("jane@example.com");
    await userEvent.clear(input);
    await userEvent.type(input, "fixed@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Save email" }));

    await waitFor(() =>
      expect(mockedApps.updateCandidateEmail).toHaveBeenCalledWith(
        "app-1",
        "fixed@example.com",
      ),
    );
  });

  it("edit-email dialog surfaces the 409 detail", async () => {
    mockedApps.updateCandidateEmail.mockRejectedValue(
      new ApiError(409, "Another candidate already uses this email"),
    );
    const menu = await openMoreActions();
    await userEvent.click(menu.getByRole("menuitem", { name: "Edit candidate email…" }));
    await userEvent.click(screen.getByRole("button", { name: "Save email" }));
    expect(
      await screen.findByText("Another candidate already uses this email"),
    ).toBeInTheDocument();
  });

describe("filters, sort and URL state", () => {
  it("sends every URL filter to the API", async () => {
    search = new URLSearchParams(
      "job=job-1&stage=screening&q=erika&score=60&quiz=completed&source=linkedin&flagged=true&days=30&sort=score_desc",
    );
    render(<ApplicantsPage />);
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenCalledWith({
        job_id: "job-1",
        stage: "screening",
        q: "erika",
        score_min: 60,
        quiz: "completed",
        source: "linkedin",
        flagged: true,
        since_days: 30,
        sort: "score_desc",
        limit: 50,
      }),
    );
    expect(screen.getByRole("button", { name: /^Screening · / })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText("Sort applicants")).toHaveValue("score_desc");
    expect(screen.getByLabelText("Score")).toHaveValue("60");
    expect(screen.getByLabelText("Search applicants")).toHaveValue("erika");
  });

  it("offers the stage-age sort and writes it to the URL", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.selectOptions(screen.getByLabelText("Sort applicants"), "Longest in stage");
    await waitFor(() => expect(replace).toHaveBeenLastCalledWith(
      "/admin/applicants?sort=stage_age_desc",
      { scroll: false },
    ));
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "stage_age_desc" }),
      ),
    );
  });

  it("changing the sort writes the URL and refetches", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.selectOptions(screen.getByLabelText("Sort applicants"), "name_asc");
    expect(replace).toHaveBeenLastCalledWith("/admin/applicants?sort=name_asc", { scroll: false });
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "name_asc" }),
      ),
    );
  });

  it("a filter from the bar narrows the request and lights the count line", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    expect(screen.getByText("2 applicants")).toBeInTheDocument();
    mockedApps.list.mockResolvedValue(pageOf([makeApp({ id: "app-1", stage: "new" })]));
    await userEvent.selectOptions(screen.getByLabelText("Quiz"), "completed");
    expect(replace).toHaveBeenLastCalledWith("/admin/applicants?quiz=completed", {
      scroll: false,
    });
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ quiz: "completed" }),
      ),
    );
    expect(await screen.findByText("1 match")).toBeInTheDocument();
  });

  it("offers the sources the server knows in the Source filter", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    const options = Array.from(
      (screen.getByLabelText("Source") as HTMLSelectElement).options,
      (option) => option.value,
    );
    expect(options).toEqual(["", "direct", "linkedin"]);
  });

  it("shows the job on each row in the all-jobs view and not in a single-job view", async () => {
    render(<ApplicantsPage />);
    const jane = await screen.findByRole("button", { name: /Jane Applicant/ });
    await waitFor(() => expect(within(jane).getByText("Backend Engineer")).toBeInTheDocument());
    expect(within(jane).getByText(/applied .* · new/)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Filter by job"), "job-1");
    const janeAgain = await screen.findByRole("button", { name: /Jane Applicant/ });
    expect(within(janeAgain).queryByText(/Backend Engineer/)).not.toBeInTheDocument();
    expect(replace).toHaveBeenLastCalledWith("/admin/applicants?job=job-1", { scroll: false });
  });

  it("shows a clearable empty state when filters match nothing", async () => {
    search = new URLSearchParams("q=nobody&flagged=true");
    mockedApps.list.mockResolvedValue(pageOf([]));
    render(<ApplicantsPage />);
    expect(await screen.findByText("No applicants match these filters.")).toBeInTheDocument();
    const clear = screen.getAllByRole("button", { name: "Clear filters" });
    await userEvent.click(clear[clear.length - 1]);
    expect(replace).toHaveBeenLastCalledWith("/admin/applicants", { scroll: false });
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenLastCalledWith({ limit: 50 }),
    );
  });

  it("keeps the plain empty state when only the stage pill narrows", async () => {
    mockedApps.list.mockResolvedValue(pageOf([]));
    render(<ApplicantsPage />);
    expect(await screen.findByText("No applications match.")).toBeInTheDocument();
  });

  it("opening an applicant writes ?selected= so the back button returns to them", async () => {
    render(<ApplicantsPage />);
    const kenji = await screen.findByRole("button", { name: /Kenji Sato/ });
    await userEvent.click(kenji);
    expect(replace).toHaveBeenLastCalledWith("/admin/applicants?selected=app-2", {
      scroll: false,
    });
    expect(kenji).toHaveAttribute("aria-current", "true");
    // the deep-link pin is a first-load affair; a row click never refetches
    expect(mockedApps.list).toHaveBeenCalledTimes(1);
  });

  it("still pins a ?selected= applicant from outside the page when a search is set", async () => {
    search = new URLSearchParams("q=jane&selected=app-9");
    mockedApps.get.mockResolvedValue(
      makeApp({
        id: "app-9",
        candidate: { id: "cand-9", name: "Far Away", email: "far@example.com", links: {} },
      }),
    );
    render(<ApplicantsPage />);
    expect(await screen.findByRole("button", { name: /Far Away/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(mockedApps.list).toHaveBeenCalledWith(expect.objectContaining({ q: "jane" }));
  });

  it("follows a query string the browser restores (back button)", async () => {
    const { rerender } = render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    search = new URLSearchParams("stage=rejected");
    rerender(<ApplicantsPage />);
    await waitFor(() =>
      expect(mockedApps.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ stage: "rejected" }),
      ),
    );
    expect(screen.getByRole("button", { name: /^Rejected · / })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

describe("bulk bar", () => {
  it("the header checkbox selects every loaded row and clears them again", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    const all = screen.getByLabelText("Select all on this page");
    await userEvent.click(all);
    expect(screen.getByLabelText("Select Jane Applicant")).toBeChecked();
    expect(screen.getByLabelText("Select Kenji Sato")).toBeChecked();
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await userEvent.click(all);
    expect(screen.getByLabelText("Select Jane Applicant")).not.toBeChecked();
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });

  it("Move to calls bulkStage with the ids, the stage and the email toggle, then reloads", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByLabelText("Select Jane Applicant"));
    await userEvent.click(screen.getByLabelText("Select Kenji Sato"));
    await userEvent.click(screen.getByLabelText("Also email candidates"));
    await userEvent.selectOptions(screen.getByLabelText("Move selected to stage"), "screening");
    await waitFor(() =>
      expect(mockedApps.bulkStage).toHaveBeenCalledWith(["app-1", "app-2"], "screening", true),
    );
    expect(await screen.findByText("Moved 2")).toBeInTheDocument();
    expect(mockedApps.list).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("2 selected")).not.toBeInTheDocument();
  });

  it("reports skipped rows after a move", async () => {
    mockedApps.bulkStage.mockResolvedValue({ updated: 1, skipped: 1 });
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByLabelText("Select all on this page"));
    await userEvent.selectOptions(screen.getByLabelText("Move selected to stage"), "interview");
    expect(await screen.findByText("Moved 1, skipped 1")).toBeInTheDocument();
  });

  it("Export CSV in the bar downloads just the selection", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByLabelText("Select all on this page"));
    const link = screen.getByRole("link", { name: "Export selected (CSV)" });
    expect(link).toHaveAttribute(
      "href",
      "/api/v1/applications/export?format=csv&ids=app-1%2Capp-2",
    );
  });

  it("the bar sticks to the bottom of the list while rows are checked", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    await userEvent.click(screen.getByLabelText("Select Jane Applicant"));
    expect(screen.getByText("1 selected").closest(".sticky")).not.toBeNull();
  });
});
});

describe("export", () => {
  beforeEach(() => {
    search = new URLSearchParams();
    mockedApi.me.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "admin@acme.dev",
      role: "admin",
      has_password: true,
    });
    mockedJobs.list.mockResolvedValue([
      { id: "job-1", title: "Backend Engineer" } as never,
      { id: "job-2", title: "Designer" } as never,
    ]);
    mockedApps.list.mockResolvedValue({
      items: [makeApp({})],
      total: 1,
      stage_counts: { new: 1 },
      sources: [],
    });
  });

  it("offers CSV and JSON downloads of the current filter", async () => {
    render(<ApplicantsPage />);
    await screen.findByRole("button", { name: /Jane Applicant/ });
    const csv = screen.getByRole("link", { name: "Export CSV" });
    const json = screen.getByRole("link", { name: "Export JSON" });
    expect(csv).toHaveAttribute("href", "/api/v1/applications/export?format=csv");
    expect(json).toHaveAttribute("href", "/api/v1/applications/export?format=json");
    expect(csv).toHaveAttribute("download");

    await userEvent.selectOptions(screen.getByLabelText("Filter by job"), "job-2");
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/v1/applications/export?format=csv&job_id=job-2",
    );

    const pill = screen.getAllByRole("button", { pressed: false })[0];
    await userEvent.click(pill);
    expect(screen.getByRole("link", { name: "Export JSON" }).getAttribute("href")).toMatch(
      /format=json&job_id=job-2&stage=[a-z_]+$/,
    );
  });
});

describe("ApplicantsPage screening answers", () => {
  const MISMATCH = {
    question_id: "sq_0000aa01",
    type: "yes_no" as const,
    prompt: "Can you work in Germany?",
    options: null,
    preferred: "yes",
    answer: "no",
    match: false,
  };

  it("shows the mismatch chip in the list and the answers block in the panel", async () => {
    mockedApps.list.mockResolvedValue(
      pageOf([makeApp({ id: "app-1", stage: "new", screening_answers: [MISMATCH] })]),
    );
    render(<ApplicantsPage />);
    const janeButton = await screen.findByRole("button", { name: /Jane Applicant/ });
    expect(within(janeButton).getByText("1 mismatch")).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Jane Applicant" });
    expect(await screen.findByText("Screening answers")).toBeInTheDocument();
    expect(screen.getByText("Can you work in Germany?")).toBeInTheDocument();
    expect(screen.getByText(/Preferred: Yes/)).toBeInTheDocument();
  });
});
