import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { questions, type BankPage, type QuestionOut } from "@/lib/api";

import QuestionsPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    questions: {
      list: vi.fn(),
      create: vi.fn(),
      retire: vi.fn(),
      bank: vi.fn(),
      block: vi.fn(),
      unblock: vi.fn(),
    },
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
  difficulty: 2,
  time_limit_seconds: 15,
  status: "active",
  created_at: "2026-07-22T10:00:00Z",
};

const bankPage: BankPage = {
  items: [
    {
      id: "py-gil-1",
      domain: "software-engineering",
      prompt_md: "What does the GIL prevent?",
      options: { a: "Parallel bytecode", b: "IO", c: "Imports", d: "GC" },
      correct_key: "a",
      explanation_md: "",
      tags: ["python"],
      difficulty: 3,
      time_limit_seconds: 15,
      blocked: false,
    },
  ],
  total: 42,
  tags: ["asyncio", "python"],
};

describe("QuestionsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.list.mockResolvedValue([existing]);
    mocked.create.mockResolvedValue({ ...existing, id: "co-new" });
    mocked.retire.mockResolvedValue({ ...existing, status: "retired" });
    mocked.bank.mockResolvedValue(bankPage);
    mocked.block.mockResolvedValue(undefined);
    mocked.unblock.mockResolvedValue(undefined);
  });

  it("defaults to the bank tab with filters and blocks a question", async () => {
    render(<QuestionsPage />);
    expect(await screen.findByText("What does the GIL prevent?")).toBeInTheDocument();
    expect(screen.getByText("1–1 of 42")).toBeInTheDocument();

    // 5-dot scale + Source pill replace the old options list
    expect(screen.getByRole("img", { name: "Difficulty 3 of 5" })).toBeInTheDocument();
    expect(screen.getByText("open bank")).toBeInTheDocument();
    expect(screen.queryByText(/✓ a\)/)).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Filter by tag"), "python");
    await waitFor(() =>
      expect(mocked.bank).toHaveBeenLastCalledWith(expect.objectContaining({ tag: "python" })),
    );

    await userEvent.click(screen.getByRole("button", { name: "Block" }));
    await waitFor(() => expect(mocked.block).toHaveBeenCalledWith("py-gil-1"));
  });

  it("clears active filters via the Clear link", async () => {
    render(<QuestionsPage />);
    await screen.findByText("What does the GIL prevent?");
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Search questions"), "gil");
    expect(await screen.findByRole("button", { name: "Clear" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() =>
      expect(mocked.bank).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined })),
    );
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });

  it("lists company questions and retires one", async () => {
    render(<QuestionsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Company questions" }));
    expect(await screen.findByText("What does our deploy script do?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(mocked.retire).toHaveBeenCalledWith("co-abc"));
  });

  it("creates a question with normalized tags", async () => {
    render(<QuestionsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Company questions" }));
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
          difficulty: 3,
          time_limit_seconds: 15,
        }),
      ),
    );
  });
});
