import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, applications, type ApplicationOut } from "@/lib/api";

import ApplicantsPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, jobs: { ...original.api.jobs, list: vi.fn() } },
    applications: { list: vi.fn(), setStage: vi.fn(), cvUrl: vi.fn(), quizAnswers: vi.fn() },
  };
});

const mockedApps = vi.mocked(applications);
const mockedJobs = vi.mocked(api.jobs);

const application: ApplicationOut = {
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
    completed_at: "2026-07-21T10:05:00Z",
    question_ids: ["q1", "q2", "q3", "q4"],
    integrity: { blur_count: 2, flags: ["left the tab 2x (~20s)"] },
  },
  created_at: "2026-07-21T10:00:00Z",
};

describe("ApplicantsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApps.list.mockResolvedValue([application]);
    mockedApps.setStage.mockResolvedValue({ ...application, stage: "screening" });
    mockedApps.cvUrl.mockResolvedValue({ download_url: "http://minio.test/cv" });
    mockedJobs.list.mockResolvedValue([
      { id: "job-1", title: "Backend Engineer" } as never,
    ]);
  });

  it("lists applicants with job title, links and CV size", async () => {
    render(<ApplicantsPage />);
    expect(await screen.findByText("Jane Applicant")).toBeInTheDocument();
    expect(screen.getByText(/Backend Engineer · applied/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "github" })).toHaveAttribute(
      "href",
      "https://github.com/jane",
    );
    expect(screen.getByRole("button", { name: /CV \(244 KB\)/ })).toBeInTheDocument();
    const badge = screen.getByText("quiz 75% (3/4)");
    expect(badge).toHaveAttribute("title", "python: 3/4");
    const warning = screen.getByText("⚠ 1");
    expect(warning).toHaveAttribute("title", "left the tab 2x (~20s)");
  });

  it("expands the answers review", async () => {
    mockedApps.quizAnswers.mockResolvedValue([
      {
        question_id: "py-gil-1",
        prompt_md: "What does the GIL prevent?",
        options: { a: "Parallel bytecode", b: "Threads", c: "Processes", d: "Races" },
        correct_key: "a",
        explanation_md: "One thread runs bytecode at a time.",
        tags: ["python"],
        answer_key: "b",
        is_correct: false,
        response_ms: 4200,
      },
      {
        question_id: "py-x-2",
        prompt_md: "Timed out one?",
        options: { a: "Yes", b: "No", c: "?", d: "!" },
        correct_key: "a",
        explanation_md: "",
        tags: ["python"],
        answer_key: null,
        is_correct: false,
        response_ms: null,
      },
    ]);
    render(<ApplicantsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Answers" }));
    expect(await screen.findByText("What does the GIL prevent?")).toBeInTheDocument();
    expect(screen.getByText(/answered: Threads \(4.2s\)/)).toBeInTheDocument();
    expect(screen.getByText(/correct: Parallel bytecode/)).toBeInTheDocument();
    expect(screen.getByText(/no answer — time ran out/)).toBeInTheDocument();
    expect(mockedApps.quizAnswers).toHaveBeenCalledWith("app-1");
  });

  it("shows pending badge for unfinished quizzes and none without a quiz", async () => {
    mockedApps.list.mockResolvedValue([
      { ...application, id: "a2", quiz_attempt: { ...application.quiz_attempt!, status: "pending", score: null } },
      { ...application, id: "a3", quiz_attempt: null },
    ]);
    render(<ApplicantsPage />);
    expect(await screen.findByText("quiz pending")).toBeInTheDocument();
    expect(screen.queryByText(/quiz \d+%/)).not.toBeInTheDocument();
  });

  it("changes the stage via the dropdown", async () => {
    render(<ApplicantsPage />);
    const select = await screen.findByLabelText("Stage for Jane Applicant");
    await userEvent.selectOptions(select, "screening");
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "screening"),
    );
  });

  it("opens the presigned CV url", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ApplicantsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /CV/ }));
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith("http://minio.test/cv", "_blank", "noopener"),
    );
  });
});
