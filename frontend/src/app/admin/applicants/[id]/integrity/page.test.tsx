import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  applications,
  type ApplicationOut,
  type QuizAnswerReview,
  type QuizResult,
} from "@/lib/api";

import IntegrityReviewPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "a1" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, jobs: { ...original.api.jobs, get: vi.fn() } },
    applications: {
      get: vi.fn(),
      quizAnswers: vi.fn(),
      reissueQuiz: vi.fn(),
      dismissFlags: vi.fn(),
      setStage: vi.fn(),
      list: vi.fn(),
      cvUrl: vi.fn(),
      remind: vi.fn(),
    },
  };
});

const mocked = vi.mocked(applications);
const mockedJobs = vi.mocked(api.jobs);

function makeAttempt(overrides: Partial<QuizResult> = {}): QuizResult {
  return {
    status: "completed",
    score: 0.74,
    per_tag_scores: {},
    completed_at: "2026-08-05T19:40:00Z",
    question_ids: ["q1", "q2", "q3"],
    integrity: {
      blur_count: 6,
      blur_total_ms: 41_000,
      paste_count: 0,
      resize_count: 2,
      avg_answer_ms: 12_000,
      flags: [
        {
          code: "tab_hidden",
          summary: "Left the tab 6 times (~41s total)",
          detail: "Most blurs landed right after the stem appeared.",
          question_ids: ["q1"],
        },
      ],
    },
    ...overrides,
  };
}

function makeApp(overrides: Partial<ApplicationOut> = {}): ApplicationOut {
  return {
    id: "a1",
    job_id: "j1",
    candidate: { id: "c1", name: "Tomas Hruby", email: "tomas@x.dev", links: {} },
    cv_filename: "cv.pdf",
    cv_size: 1000,
    message: null,
    stage: "screening",
    source: null,
    quiz_attempt: makeAttempt(),
    created_at: "2026-08-05T18:00:00Z",
    ...overrides,
  } as ApplicationOut;
}

const answers: QuizAnswerReview[] = [
  {
    question_id: "q1",
    prompt_md: "Q1",
    options: {},
    correct_key: "a",
    explanation_md: "",
    tags: [],
    answer_key: "a",
    is_correct: true,
    response_ms: 14_000,
    integrity_events: [{ type: "blur", duration_ms: 8000 }],
  },
  {
    question_id: "q2",
    prompt_md: "Q2",
    options: {},
    correct_key: "b",
    explanation_md: "",
    tags: [],
    answer_key: "c",
    is_correct: false,
    response_ms: 9000,
    integrity_events: [],
  },
  {
    question_id: "q3",
    prompt_md: "Q3",
    options: {},
    correct_key: "a",
    explanation_md: "",
    tags: [],
    answer_key: "a",
    is_correct: true,
    response_ms: 11_000,
    integrity_events: [{ type: "resize", duration_ms: null }],
  },
];

describe("IntegrityReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(makeApp());
    mocked.quizAnswers.mockResolvedValue(answers);
    mocked.dismissFlags.mockResolvedValue(makeAttempt());
    mocked.reissueQuiz.mockResolvedValue(makeAttempt({ status: "pending" }));
    mocked.setStage.mockResolvedValue(makeApp({ stage: "rejected" }));
    mockedJobs.get.mockResolvedValue({ title: "Backend Engineer (Python)" } as never);
  });

  it("renders header, stat cards, timeline, event log, and flag callout", async () => {
    render(<IntegrityReviewPage />);
    expect(await screen.findByText("Tomas Hruby")).toBeInTheDocument();
    expect(screen.getByText("needs review")).toBeInTheDocument();
    expect(await screen.findByText(/Backend Engineer \(Python\) quiz/)).toBeInTheDocument();
    expect(screen.getByText("74")).toBeInTheDocument();
    expect(screen.getByText("Window blurs")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("0:41")).toBeInTheDocument();
    expect(await screen.findByText("Session timeline")).toBeInTheDocument();
    expect(screen.getByText("Event log")).toBeInTheDocument();
    expect(screen.getByText("window blur")).toBeInTheDocument();
    expect(screen.getByText("8s away")).toBeInTheDocument();
    expect(screen.getByText("Left the tab 6 times (~41s total)")).toBeInTheDocument();
  });

  it("dismisses flags", async () => {
    render(<IntegrityReviewPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Dismiss flags — looks fine" }),
    );
    await waitFor(() => expect(mocked.dismissFlags).toHaveBeenCalledWith("a1"));
  });

  it("shows the reviewed state instead of needs-review once dismissed", async () => {
    mocked.get.mockResolvedValue(
      makeApp({
        quiz_attempt: makeAttempt({
          integrity: {
            ...makeAttempt().integrity,
            review: { decision: "dismissed", by_user_id: "u1", at: "2026-08-06T10:00:00Z" },
          },
        }),
      }),
    );
    render(<IntegrityReviewPage />);
    expect(await screen.findByText("flags dismissed")).toBeInTheDocument();
    expect(screen.queryByText("needs review")).not.toBeInTheDocument();
  });

  it("re-invites only after an explicit confirm", async () => {
    render(<IntegrityReviewPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Invalidate & re-invite to a fresh quiz" }),
    );
    expect(mocked.reissueQuiz).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Confirm — invalidate this attempt and email a fresh quiz",
      }),
    );
    await waitFor(() => expect(mocked.reissueQuiz).toHaveBeenCalledWith("a1"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Fresh quiz sent to tomas@x.dev",
    );
  });

  it("rejects only after an explicit confirm", async () => {
    render(<IntegrityReviewPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reject application…" }));
    expect(mocked.setStage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm reject" }));
    await waitFor(() => expect(mocked.setStage).toHaveBeenCalledWith("a1", "rejected"));
  });

  it("shows re-issue provenance chips on a re-issued attempt", async () => {
    mocked.get.mockResolvedValue(
      makeApp({
        quiz_attempt: makeAttempt({
          status: "pending",
          score: null,
          completed_at: null,
          integrity: {
            reissue: {
              from_attempt_id: "old",
              reason: "expired",
              mode: "auto",
              by_user_id: null,
              at: "2026-08-06T10:00:00Z",
            },
            reissue_requested: undefined,
          },
        }),
      }),
    );
    render(<IntegrityReviewPage />);
    expect(await screen.findByText("re-issued (link expired, auto)")).toBeInTheDocument();
    expect(mocked.quizAnswers).not.toHaveBeenCalled();
  });
});
