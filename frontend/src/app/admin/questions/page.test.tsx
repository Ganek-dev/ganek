import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { questions, type QuestionOut } from "@/lib/api";

import QuestionsPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    questions: { list: vi.fn(), create: vi.fn(), retire: vi.fn() },
  };
});

const mocked = vi.mocked(questions);

const existing: QuestionOut = {
  id: "co-abc",
  prompt_md: "What does our deploy script do?",
  options: { a: "Deploys", b: "Builds", c: "Tests", d: "Nothing" },
  correct_key: "a",
  explanation_md: "",
  tags: ["internal"],
  difficulty: "easy",
  time_limit_seconds: 15,
  status: "active",
  created_at: "2026-07-22T10:00:00Z",
};

describe("QuestionsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.list.mockResolvedValue([existing]);
    mocked.create.mockResolvedValue({ ...existing, id: "co-new" });
    mocked.retire.mockResolvedValue({ ...existing, status: "retired" });
  });

  it("lists questions and retires one", async () => {
    render(<QuestionsPage />);
    expect(await screen.findByText("What does our deploy script do?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(mocked.retire).toHaveBeenCalledWith("co-abc"));
  });

  it("creates a question with normalized tags", async () => {
    render(<QuestionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "New question" }));
    await userEvent.type(
      screen.getByLabelText(/Question \(markdown/),
      "What is our style guide?",
    );
    await userEvent.type(screen.getByLabelText("Option A"), "PEP8");
    await userEvent.type(screen.getByLabelText("Option B"), "Chaos");
    await userEvent.type(screen.getByLabelText("Option C"), "Tabs");
    await userEvent.type(screen.getByLabelText("Option D"), "None");
    await userEvent.type(screen.getByLabelText("Tags"), " Internal, style ");
    await userEvent.click(screen.getByRole("button", { name: "Create question" }));

    await waitFor(() =>
      expect(mocked.create).toHaveBeenCalledWith(
        expect.objectContaining({
          prompt_md: "What is our style guide?",
          options: { a: "PEP8", b: "Chaos", c: "Tabs", d: "None" },
          correct_key: "a",
          tags: ["internal", "style"],
          difficulty: "medium",
          time_limit_seconds: 15,
        }),
      ),
    );
  });
});
