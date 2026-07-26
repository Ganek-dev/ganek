import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  questionnaires,
  questions,
  type BankPage,
  type QuestionnaireOut,
  type ResolvedQuestion,
} from "@/lib/api";

import QuestionnaireBuilderPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: "q1" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    questionnaires: {
      list: vi.fn(),
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    questions: {
      ...original.questions,
      bank: vi.fn(),
      resolve: vi.fn(),
    },
  };
});

const mockedQnr = vi.mocked(questionnaires);
const mockedQ = vi.mocked(questions);

function baseQuestionnaire(overrides: Partial<QuestionnaireOut> = {}): QuestionnaireOut {
  return {
    id: "q1",
    name: "Frontend basics v2",
    description: "",
    shuffle: false,
    question_refs: ["py-gil-1", "js-closure-3"],
    created_at: "2026-07-25T10:00:00Z",
    updated_at: "2026-07-25T10:00:00Z",
    ...overrides,
  };
}

const RESOLVED: ResolvedQuestion[] = [
  {
    id: "py-gil-1",
    prompt_md: "What does the GIL prevent?",
    tags: ["python"],
    difficulty: 2,
    time_limit_seconds: 15,
    source: "seed",
    status: "active",
    blocked: false,
  },
  {
    id: "js-closure-3",
    prompt_md: "Which of these captures `i` by value?",
    tags: ["javascript"],
    difficulty: 3,
    time_limit_seconds: 20,
    source: "seed",
    status: "active",
    blocked: false,
  },
];

const BANK: BankPage = {
  items: [
    {
      id: "py-gil-1",
      domain: "software-engineering",
      prompt_md: "What does the GIL prevent?",
      options: { a: "A", b: "B", c: "C", d: "D" },
      correct_key: "a",
      explanation_md: "",
      tags: ["python"],
      difficulty: 2,
      time_limit_seconds: 15,
      blocked: false,
    },
    {
      id: "py-list-alias-1",
      domain: "software-engineering",
      prompt_md: "Aliasing pitfall",
      options: { a: "A", b: "B", c: "C", d: "D" },
      correct_key: "a",
      explanation_md: "",
      tags: ["python"],
      difficulty: 2,
      time_limit_seconds: 15,
      blocked: false,
    },
  ],
  total: 2,
  tags: ["javascript", "python"],
};

describe("QuestionnaireBuilderPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockedQnr.get.mockResolvedValue(baseQuestionnaire());
    mockedQnr.update.mockImplementation(async (_id, patch) =>
      baseQuestionnaire({
        name: patch.name ?? "Frontend basics v2",
        shuffle: patch.shuffle ?? false,
        question_refs: patch.question_refs ?? ["py-gil-1", "js-closure-3"],
      }),
    );
    mockedQnr.delete.mockResolvedValue();
    mockedQ.resolve.mockResolvedValue(RESOLVED);
    mockedQ.bank.mockResolvedValue(BANK);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the header, mix bar and each ref as a row", async () => {
    render(<QuestionnaireBuilderPage />);
    expect(await screen.findByLabelText("Questionnaire name")).toHaveValue(
      "Frontend basics v2",
    );
    expect(await screen.findByText("What does the GIL prevent?")).toBeInTheDocument();
    expect(screen.getByText(/Which of these captures/)).toBeInTheDocument();
    // difficulty-mix summary: 1 easy (d2), 1 medium (d3), 0 hard, 35s total
    expect(screen.getByText(/2 questions · 1 easy · 1 medium · 0 hard · 35s total/))
      .toBeInTheDocument();
  });

  it("adds a library question, removes an existing one, and PATCHes debounced", async () => {
    render(<QuestionnaireBuilderPage />);
    await screen.findAllByText("What does the GIL prevent?");

    // second library row (py-list-alias-1) is not yet in refs → shows +Add
    await userEvent.click(screen.getByRole("button", { name: "+ Add" }));

    // remove the first attached row by targeting its Remove button directly
    const removeButtons = screen.getAllByRole("button", {
      name: "Remove from questionnaire",
    });
    await userEvent.click(removeButtons[0]);

    // debounce ⇒ single PATCH after 600ms with the final ref list
    vi.advanceTimersByTime(700);
    await waitFor(() => expect(mockedQnr.update).toHaveBeenCalledTimes(1));
    expect(mockedQnr.update.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        question_refs: ["js-closure-3", "py-list-alias-1"],
      }),
    );
  });

  it("toggling shuffle triggers a PATCH with shuffle:true", async () => {
    render(<QuestionnaireBuilderPage />);
    await screen.findByText("What does the GIL prevent?");
    await userEvent.click(screen.getByRole("switch", { name: "Shuffle question order" }));

    vi.advanceTimersByTime(700);
    await waitFor(() => expect(mockedQnr.update).toHaveBeenCalled());
    expect(mockedQnr.update.mock.calls.at(-1)![1]).toEqual(
      expect.objectContaining({ shuffle: true }),
    );
  });

  it("renders a warning row for refs the workspace can no longer see", async () => {
    mockedQnr.get.mockResolvedValueOnce(
      baseQuestionnaire({ question_refs: ["py-gil-1", "ghost-ref"] }),
    );
    // Only py-gil-1 resolves — ghost-ref stays missing after the promise settles.
    mockedQ.resolve.mockResolvedValueOnce([RESOLVED[0]]);
    render(<QuestionnaireBuilderPage />);

    // Poll until exactly one "missing" warning is present (py-gil-1 has
    // resolved, ghost-ref hasn't) — waiting on `findByText` for the GIL prompt
    // is not enough because the library sidebar also renders that prompt.
    await waitFor(() =>
      expect(
        screen.queryAllByText(/not visible to this workspace — remove to clean up/),
      ).toHaveLength(1),
    );
    expect(screen.getByText("Missing question ghost-ref")).toBeInTheDocument();
    expect(screen.queryByText("Missing question py-gil-1")).not.toBeInTheDocument();
  });

  it("deletes and routes back to the index", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<QuestionnaireBuilderPage />);
    await screen.findByText("What does the GIL prevent?");
    await userEvent.click(screen.getByRole("button", { name: /Delete/ }));
    await waitFor(() => expect(mockedQnr.delete).toHaveBeenCalledWith("q1"));
    expect(push).toHaveBeenCalledWith("/admin/questionnaires");
    confirm.mockRestore();
  });
});
