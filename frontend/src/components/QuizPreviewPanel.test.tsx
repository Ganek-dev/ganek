import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type JobOut, type QuizPreview } from "@/lib/api";

import { QuizPreviewPanel } from "./QuizPreviewPanel";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      jobs: { ...original.api.jobs, quizPreview: vi.fn(), get: vi.fn(), update: vi.fn() },
    },
  };
});

const mockedJobs = vi.mocked(api.jobs);

const JOB_ID = "11111111-1111-1111-1111-111111111111";

const preview: QuizPreview = {
  enabled: true,
  tags: ["python"],
  question_count: 2,
  time_limit_seconds: 25,
  difficulties: [],
  pool: [
    {
      id: "py-gil-1",
      source: "seed",
      tags: ["python"],
      difficulty: 3,
      prompt_md: "What does the GIL prevent?",
      options: { a: "Parallel bytecode", b: "IO", c: "Imports", d: "GC" },
      correct_key: "a",
      excluded: false,
      blocked: false,
    },
    {
      id: "py-dec-1",
      source: "seed",
      tags: ["python"],
      difficulty: 1,
      prompt_md: "What does @property do?",
      options: { a: "Getter", b: "Setter", c: "Deleter", d: "Nothing" },
      correct_key: "a",
      excluded: false,
      blocked: true,
    },
  ],
  eligible_count: 1,
  eligible_by_tag: { python: 1 },
  sample_question_ids: ["py-gil-1"],
};

const job = {
  id: JOB_ID,
  quiz_config: {
    enabled: true,
    tags: ["python"],
    question_count: 2,
    include_company_questions: true,
    time_limit_seconds: 25,
    difficulties: null,
    exclude_ids: [],
    questionnaire_id: null,
  },
} as unknown as JobOut;

describe("QuizPreviewPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedJobs.quizPreview.mockResolvedValue(preview);
    mockedJobs.get.mockResolvedValue(job);
    mockedJobs.update.mockResolvedValue(job);
  });

  it("shows the sample, pool stats, and timer", async () => {
    render(<QuizPreviewPanel jobId={JOB_ID} />);
    expect(await screen.findByText("What does the GIL prevent?")).toBeInTheDocument();
    expect(screen.getByText(/1 eligible question/)).toBeInTheDocument();
    expect(screen.getByText(/python: 1/)).toBeInTheDocument();
    expect(screen.getByText(/25s per question/)).toBeInTheDocument();
    // sample view hides the blocked question; pool view shows it
    expect(screen.queryByText("What does @property do?")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Show pool/ }));
    expect(screen.getByText("What does @property do?")).toBeInTheDocument();
    expect(screen.getByText("blocked company-wide")).toBeInTheDocument();
  });

  it("excludes a question via PATCH on the job quiz_config", async () => {
    render(<QuizPreviewPanel jobId={JOB_ID} />);
    await screen.findByText("What does the GIL prevent?");
    await userEvent.click(screen.getByRole("button", { name: "Exclude" }));
    await waitFor(() =>
      expect(mockedJobs.update).toHaveBeenCalledWith(JOB_ID, {
        quiz_config: expect.objectContaining({ exclude_ids: ["py-gil-1"] }),
      }),
    );
  });
});
