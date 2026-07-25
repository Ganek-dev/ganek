import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { publicQuiz, type QuizQuestion } from "@/lib/api";

import QuizPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok-123" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    publicQuiz: { state: vi.fn(), next: vi.fn(), answer: vi.fn(), events: vi.fn() },
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

function lockButton() {
  // desktop + mobile lock buttons both exist in the DOM; either works
  return screen.getAllByRole("button", { name: /Lock answer/ })[0];
}

describe("QuizPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.state.mockResolvedValue({ status: "pending", answered: 0, total: 2 });
    mocked.answer.mockResolvedValue({ recorded: true });
    mocked.events.mockResolvedValue({ recorded: true });
  });

  it("shows the intro with the rules, then serves a question", async () => {
    mocked.next.mockResolvedValue({ done: false, question });
    render(<QuizPage />);
    expect(await screen.findByText("Quick skills check")).toBeInTheDocument();
    expect(screen.getByText(/2 multiple-choice questions/)).toBeInTheDocument();
    expect(screen.getByText(/tab switches are recorded/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Start the quiz" }));
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
    await userEvent.click(await screen.findByRole("button", { name: "Start the quiz" }));
    await screen.findByText(/Question 1/);

    expect(lockButton()).toBeDisabled();
    expect(mocked.answer).not.toHaveBeenCalled();
  });

  it("selects an option, locks it, and advances to done", async () => {
    mocked.next
      .mockResolvedValueOnce({ done: false, question })
      .mockResolvedValueOnce({ done: true, question: null });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Start the quiz" }));

    const option = await screen.findByRole("button", { name: /Any use of threads/ });
    await userEvent.click(option);
    expect(option).toHaveAttribute("aria-pressed", "true");
    expect(mocked.answer).not.toHaveBeenCalled(); // selecting is not locking

    await userEvent.click(lockButton());
    await waitFor(() =>
      expect(mocked.answer).toHaveBeenCalledWith("tok-123", "py-gil-1", "c"),
    );
    expect(await screen.findByText(/Quiz completed/)).toBeInTheDocument();
  });

  it("supports A–D selection and Enter to lock", async () => {
    mocked.next
      .mockResolvedValueOnce({ done: false, question })
      .mockResolvedValueOnce({ done: true, question: null });
    render(<QuizPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Start the quiz" }));
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
    mocked.state.mockResolvedValue({ status: "completed", answered: 2, total: 2 });
    render(<QuizPage />);
    expect(await screen.findByText(/Quiz completed/)).toBeInTheDocument();
    expect(mocked.next).not.toHaveBeenCalled();
  });
});
