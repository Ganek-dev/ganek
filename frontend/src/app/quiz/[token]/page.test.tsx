import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  publicQuiz,
  type PracticeQuestion,
  type QuizQuestion,
  type QuizState,
} from "@/lib/api";

import QuizPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok-123" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    publicQuiz: {
      state: vi.fn(),
      next: vi.fn(),
      answer: vi.fn(),
      events: vi.fn(),
      practice: vi.fn(),
      requestReissue: vi.fn(),
    },
  };
});

const mocked = vi.mocked(publicQuiz);

const question: QuizQuestion = {
  id: "py-gil-1",
  prompt_md: "What does the GIL prevent?",
  options: [
    { key: "c", text_md: "Any use of threads" },
    { key: "a", text_md: "Parallel bytecode execution" },
    { key: "b", text_md: "Multiple processes" },
    { key: "d", text_md: "Race conditions" },
  ],
  time_limit_seconds: 15,
  deadline_at: new Date(Date.now() + 17000).toISOString(),
  index: 1,
  total: 2,
};

function makeState(overrides: Partial<QuizState> = {}): QuizState {
  return {
    status: "pending",
    answered: 0,
    total: 2,
    candidate_name: "Jane Applicant",
    company_name: "Quiz Co",
    job_title: "Python Dev",
    brand_primary: "#3d5afe",
    seconds_per_question: 15,
    expires_at: new Date(Date.now() + 20 * 60 * 60 * 1000).toISOString(),
    practice_available: true,
    status_token: "st-tok",
    ...overrides,
  };
}

function lockButton() {
  // desktop + mobile lock buttons both exist in the DOM; either works
  return screen.getAllByRole("button", { name: /Lock answer/ })[0];
}

describe("QuizPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.state.mockResolvedValue(makeState());
    mocked.answer.mockResolvedValue({ recorded: true });
    mocked.events.mockResolvedValue({ recorded: true });
  });

  it("shows the start gate with the rules, then serves a question", async () => {
    mocked.next.mockResolvedValue({ done: false, question });
    render(<QuizPage />);
    expect(await screen.findByText("Ready when you are, Jane")).toBeInTheDocument();
    expect(screen.getByText(/no pause button/)).toBeInTheDocument();
    expect(screen.getByText(/questions — single choice/)).toBeInTheDocument();
    expect(screen.getByText(/locks automatically at 0:00/)).toBeInTheDocument();
    // complete monitoring disclosure — pastes included (M5.6 G1 transparency fix)
    expect(
      screen.getByText(/tab switches \(and how long\), pastes, and window resizes/),
    ).toBeInTheDocument();
    expect(screen.getByText(/nothing auto-rejects/)).toBeInTheDocument();
    expect(screen.getByText("Quiz Co")).toBeInTheDocument();
    // postpone AND skip are both stated — the LIA's objection route (M5.6 G5)
    expect(
      screen.getByText(/come back with the same link.*application still stands/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Start the real assessment" }));
    expect(await screen.findByText(/Question 1/)).toBeInTheDocument();
    expect(screen.getByText("What does the GIL prevent?")).toBeInTheDocument();
    // options rendered in served order, lettered A–D
    const optionA = screen.getByRole("button", { name: /Any use of threads/ });
    expect(optionA).toHaveTextContent(/^A/);
    expect(screen.getByLabelText("time remaining")).toBeInTheDocument();
  });

  it("locks nothing until an option is selected", async () => {
    mocked.next.mockResolvedValue({ done: false, question });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Start the real assessment" }));
    await screen.findByText(/Question 1/);

    expect(lockButton()).toBeDisabled();
    expect(mocked.answer).not.toHaveBeenCalled();
  });

  it("selects an option, locks it, and advances to done", async () => {
    mocked.next
      .mockResolvedValueOnce({ done: false, question })
      .mockResolvedValueOnce({ done: true, question: null });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Start the real assessment" }));

    const option = await screen.findByRole("button", { name: /Any use of threads/ });
    await userEvent.click(option);
    expect(option).toHaveAttribute("aria-pressed", "true");
    expect(mocked.answer).not.toHaveBeenCalled(); // selecting is not locking

    await userEvent.click(lockButton());
    await waitFor(() =>
      expect(mocked.answer).toHaveBeenCalledWith("tok-123", "py-gil-1", "c"),
    );
    expect(await screen.findByText(/submitted/)).toBeInTheDocument();
    expect(screen.getByText(/What happens next/i)).toBeInTheDocument();
    expect(screen.queryByText(/%|score/i)).toBeNull(); // no score, ever
  });

  it("carries the company brand through the exam and finished screens", async () => {
    // the timer ring and lock CTA derive from --brand-primary; intro/practice
    // always had it — the question and done phases silently dropped it
    mocked.next
      .mockResolvedValueOnce({ done: false, question })
      .mockResolvedValueOnce({ done: true, question: null });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Start the real assessment" }));
    await screen.findByText(/Question 1/);
    const examMain = document.querySelector("main") as HTMLElement;
    expect(examMain.style.getPropertyValue("--brand-primary")).toBe("#3d5afe");

    await userEvent.click(screen.getByRole("button", { name: /Any use of threads/ }));
    await userEvent.click(lockButton());
    await screen.findByText(/submitted/);
    const doneMain = document.querySelector("main") as HTMLElement;
    expect(doneMain.style.getPropertyValue("--brand-primary")).toBe("#3d5afe");
  });

  it("supports A–D selection and Enter to lock", async () => {
    mocked.next
      .mockResolvedValueOnce({ done: false, question })
      .mockResolvedValueOnce({ done: true, question: null });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Start the real assessment" }));
    await screen.findByText(/Question 1/);

    await userEvent.keyboard("b");
    expect(screen.getByRole("button", { name: /Parallel bytecode/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(mocked.answer).toHaveBeenCalledWith("tok-123", "py-gil-1", "a"),
    );
  });

  it("shows the completed state directly for finished attempts", async () => {
    mocked.state.mockResolvedValue(makeState({ status: "completed", answered: 2 }));
    render(<QuizPage />);
    expect(await screen.findByText(/submitted/)).toBeInTheDocument();
    expect(screen.getByText("2 of 2 answered")).toBeInTheDocument();
    expect(mocked.next).not.toHaveBeenCalled();
    // finished screen links the status page
    expect(screen.getByRole("link", { name: /track your application/i })).toHaveAttribute(
      "href",
      "/application/st-tok",
    );
  });

  it("shows the expired-link state for expired attempts", async () => {
    mocked.state.mockResolvedValue(makeState({ status: "expired" }));
    render(<QuizPage />);
    expect(await screen.findByText(/This assessment link expired/)).toBeInTheDocument();
    expect(screen.getByText(/application itself was received/)).toBeInTheDocument();
  });

  it("requests a new link — auto mode confirms the email", async () => {
    mocked.state.mockResolvedValue(makeState({ status: "expired" }));
    mocked.requestReissue.mockResolvedValue({ reissued: true });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Request a new link" }));
    await waitFor(() => expect(mocked.requestReissue).toHaveBeenCalledWith("tok-123"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "A fresh link is on its way — check your inbox.",
    );
  });

  it("requests a new link — manual mode says the team was notified", async () => {
    mocked.state.mockResolvedValue(makeState({ status: "expired" }));
    mocked.requestReissue.mockResolvedValue({ reissued: false });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Request a new link" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "The hiring team has been notified",
    );
  });

  it("a 409 on request means a link was already re-issued", async () => {
    mocked.state.mockResolvedValue(makeState({ status: "expired" }));
    mocked.requestReissue.mockRejectedValue(new ApiError(409, "already issued"));
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Request a new link" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "A new link was already issued — check your inbox.",
    );
  });
});

describe("practice run", () => {
  const practiceQuestion: PracticeQuestion = {
    id: "js-arr-1",
    prompt_md: "Which array method returns a new array?",
    options: [
      { key: "a", text_md: "sort()" },
      { key: "b", text_md: "toSorted()" },
      { key: "c", text_md: "splice()" },
      { key: "d", text_md: "reverse()" },
    ],
    time_limit_seconds: 15,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocked.state.mockResolvedValue(makeState());
    mocked.practice.mockResolvedValue({ question: practiceQuestion });
    mocked.answer.mockResolvedValue({ recorded: true });
    mocked.events.mockResolvedValue({ recorded: true });
  });

  it("hides the practice button when no practice pool exists", async () => {
    mocked.state.mockResolvedValue(makeState({ practice_available: false }));
    render(<QuizPage />);
    await screen.findByText("Ready when you are, Jane");
    expect(screen.queryByRole("button", { name: /practice run/i })).not.toBeInTheDocument();
  });

  it("runs an unrecorded practice question: pick locks, nothing is submitted", async () => {
    mocked.next.mockResolvedValue({ done: false, question });
    render(<QuizPage />);
    await screen.findByText("Ready when you are, Jane");

    await userEvent.click(screen.getByRole("button", { name: /Try a practice run first/ }));
    expect(await screen.findByText("Practice — not recorded")).toBeInTheDocument();
    expect(screen.getByText("Which array method returns a new array?")).toBeInTheDocument();
    expect(screen.getByText(/never revealed/)).toBeInTheDocument();

    // picking locks immediately — and never calls the real answer endpoint
    await userEvent.click(screen.getByRole("button", { name: /toSorted/ }));
    expect(await screen.findByText(/your answer — locked/)).toBeInTheDocument();
    expect(mocked.answer).not.toHaveBeenCalled();
    expect(mocked.events).not.toHaveBeenCalled();

    // another practice question re-fetches
    await userEvent.click(screen.getByRole("button", { name: /Another practice question/ }));
    await waitFor(() => expect(mocked.practice).toHaveBeenCalledTimes(2));

    // and the real assessment can start from here
    await userEvent.click(
      screen.getByRole("button", { name: /I'm ready — start the real assessment/ }),
    );
    expect(await screen.findByText(/Question 1/)).toBeInTheDocument();
    expect(mocked.next).toHaveBeenCalledTimes(1);
  });
});
