import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, review, scorecards, type ReviewApplicationOut, type Scorecard } from "@/lib/api";

import ReviewDetailPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ applicationId: "a1" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    review: { list: vi.fn(), get: vi.fn() },
    scorecards: { ...original.scorecards, submit: vi.fn(), decline: vi.fn() },
  };
});

const mockedReview = vi.mocked(review);
const mockedCards = vi.mocked(scorecards);

const criteria = [{ id: "c1", label: "Problem solving", hint: "" }];

function card(over: Partial<Scorecard>): Scorecard {
  return {
    id: "s1",
    application_id: "a1",
    reviewer_user_id: "u1",
    reviewer_label: "Max Berger",
    requested_by_label: null,
    interview_id: null,
    requested_at: "2026-10-30T10:00:00Z",
    due_from: "2026-10-30T10:00:00Z",
    submitted_at: null,
    dismissed_at: null,
    declined_at: null,
    state: "open",
    waiting_days: 1,
    criteria,
    ratings: {},
    recommendation: null,
    comment: null,
    edited: false,
    can_edit: false,
    ...over,
  };
}

function detail(over: Partial<ReviewApplicationOut> = {}): ReviewApplicationOut {
  return {
    application_id: "a1",
    candidate_name: "Ada Lovelace",
    job_title: "Backend Engineer",
    cv_url: "https://files.example/cv.pdf",
    screening_answers: [{ prompt: "Work permit?", answer: "Needs sponsorship" }],
    quiz: {
      score: 0.75,
      correct: 6,
      total: 8,
      timed_out: 2,
      questions: [
        { prompt: "What is a mutex?", outcome: "correct" },
        { prompt: "Explain CAP", outcome: "wrong" },
        { prompt: "Big-O of sort", outcome: "timed_out" },
      ],
    },
    interview: {
      scheduled_start: "2026-11-03T09:00:00Z",
      duration_minutes: 45,
      location: "Room 2",
      timezone: "Europe/Berlin",
    },
    mine: card({}),
    others: [],
    hidden_until_submitted: true,
    ...over,
  };
}

describe("ReviewDetailPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows skeletons while loading", () => {
    mockedReview.get.mockReturnValue(new Promise(() => {}));
    render(<ReviewDetailPage />);
    expect(screen.getAllByTestId("review-skeleton").length).toBeGreaterThan(0);
  });

  it("renders the judging view", async () => {
    mockedReview.get.mockResolvedValue(detail());
    render(<ReviewDetailPage />);
    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByText("Backend Engineer")).toBeInTheDocument();
    const cv = screen.getByRole("link", { name: /Open CV/ });
    expect(cv).toHaveAttribute("href", "https://files.example/cv.pdf");
    expect(cv).toHaveAttribute("target", "_blank");
    expect(cv).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText("Work permit?")).toBeInTheDocument();
    expect(screen.getByText("Needs sponsorship")).toBeInTheDocument();
    expect(screen.getByText("6 of 8 correct, 2 timed out")).toBeInTheDocument();
    expect(screen.getByText("What is a mutex?")).toBeInTheDocument();
    expect(screen.getByText("Explain CAP")).toBeInTheDocument();
    expect(screen.getByText(/45 min/)).toBeInTheDocument();
    expect(screen.getByText(/3 Nov 2026, 10:00/)).toBeInTheDocument();
    expect(screen.getByText(/Europe\/Berlin/)).toBeInTheDocument();
    expect(screen.getByText(/Room 2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit scorecard" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "I did not assess this candidate" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Colleagues' scorecards appear after you submit yours."),
    ).toBeInTheDocument();
  });

  it("omits the CV link, quiz and interview when absent", async () => {
    mockedReview.get.mockResolvedValue(detail({ cv_url: null, quiz: null, interview: null }));
    render(<ReviewDetailPage />);
    await screen.findByRole("heading", { name: "Ada Lovelace" });
    expect(screen.queryByRole("link", { name: /Open CV/ })).not.toBeInTheDocument();
    expect(screen.getByText("No completed quiz")).toBeInTheDocument();
    expect(screen.queryByText(/min/)).not.toBeInTheDocument();
  });

  it("shows no form or decline link without an own row", async () => {
    mockedReview.get.mockResolvedValue(detail({ mine: null, hidden_until_submitted: true }));
    render(<ReviewDetailPage />);
    await screen.findByRole("heading", { name: "Ada Lovelace" });
    expect(screen.queryByRole("button", { name: "Submit scorecard" })).not.toBeInTheDocument();
    expect(screen.queryByText(/did not assess/)).not.toBeInTheDocument();
  });

  it("submits, then reloads from the server and shows colleagues' cards", async () => {
    const user = userEvent.setup();
    const submitted = card({
      state: "submitted",
      submitted_at: "2026-11-01T10:00:00Z",
      ratings: { c1: 3 },
      recommendation: "yes",
      comment: "Solid",
      can_edit: true,
    });
    mockedReview.get
      .mockResolvedValueOnce(detail())
      .mockResolvedValueOnce(
        detail({
          mine: submitted,
          hidden_until_submitted: false,
          others: [
            card({
              id: "s2",
              reviewer_label: "Erika",
              state: "submitted",
              submitted_at: "2026-11-01T09:00:00Z",
              ratings: { c1: 4 },
              recommendation: "strong_yes",
            }),
          ],
        }),
      );
    mockedCards.submit.mockResolvedValue(submitted);
    render(<ReviewDetailPage />);
    await screen.findByRole("heading", { name: "Ada Lovelace" });
    await user.click(screen.getByLabelText("3 of 4"));
    await user.click(screen.getByRole("button", { name: "Yes" }));
    await user.click(screen.getByRole("button", { name: "Submit scorecard" }));
    expect(mockedCards.submit).toHaveBeenCalledWith("a1", {
      ratings: { c1: 3 },
      recommendation: "yes",
      comment: null,
    });
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(mockedReview.get).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Erika")).toBeInTheDocument();
    expect(screen.getByText("Strong yes")).toBeInTheDocument();
    expect(screen.getByLabelText("4 of 4")).toBeInTheDocument();
    expect(screen.queryByText(/appear after you submit/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit scorecard" })).not.toBeInTheDocument();
  });

  it("edits a submitted scorecard while can_edit", async () => {
    const user = userEvent.setup();
    const mine = card({
      state: "submitted",
      submitted_at: "2026-11-01T10:00:00Z",
      ratings: { c1: 2 },
      recommendation: "no",
      can_edit: true,
    });
    mockedReview.get.mockResolvedValue(detail({ mine, hidden_until_submitted: false }));
    mockedCards.submit.mockResolvedValue(mine);
    render(<ReviewDetailPage />);
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(mockedCards.submit).toHaveBeenCalledWith("a1", {
      ratings: { c1: 2 },
      recommendation: "no",
      comment: null,
    });
    await waitFor(() => expect(mockedReview.get).toHaveBeenCalledTimes(2));
  });

  it("hides Edit once can_edit is false", async () => {
    const mine = card({ state: "submitted", recommendation: "yes", can_edit: false });
    mockedReview.get.mockResolvedValue(detail({ mine, hidden_until_submitted: false }));
    render(<ReviewDetailPage />);
    await screen.findByRole("heading", { name: "Ada Lovelace" });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("declines and shows the declined state, keeping the view", async () => {
    const user = userEvent.setup();
    mockedReview.get
      .mockResolvedValueOnce(detail())
      .mockResolvedValueOnce(
        detail({ mine: card({ state: "declined", declined_at: "2026-11-01T10:00:00Z" }) }),
      );
    mockedCards.decline.mockResolvedValue(undefined);
    render(<ReviewDetailPage />);
    await user.click(
      await screen.findByRole("button", { name: "I did not assess this candidate" }),
    );
    expect(mockedCards.decline).toHaveBeenCalledWith("a1");
    expect(await screen.findByText("You declined to assess this candidate.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit scorecard" })).not.toBeInTheDocument();
    expect(screen.getByText("Work permit?")).toBeInTheDocument();
  });

  it("shows a not-available state with a way back on 404", async () => {
    mockedReview.get.mockRejectedValue(new ApiError(404, "Not found"));
    render(<ReviewDetailPage />);
    expect(await screen.findByText("This candidate is not available")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to your candidates/ })).toHaveAttribute(
      "href",
      "/review",
    );
  });

  it("shows a retryable error on other failures", async () => {
    mockedReview.get.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(detail());
    const user = userEvent.setup();
    render(<ReviewDetailPage />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/boom/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
  });
});
