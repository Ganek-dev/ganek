import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  questionnaires,
  questions,
  type JobInput,
  type JobOut,
  type QuestionnaireOut,
  type ResolvedQuestion,
} from "@/lib/api";

import { JobForm } from "./JobForm";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    questionnaires: { ...original.questionnaires, list: vi.fn() },
    questions: { ...original.questions, resolve: vi.fn() },
  };
});

const mockedQnr = vi.mocked(questionnaires);
const mockedQ = vi.mocked(questions);

const SAMPLE_QUESTIONNAIRE: QuestionnaireOut = {
  id: "qnr-1",
  name: "Frontend basics v2",
  description: "",
  shuffle: false,
  question_refs: ["py-gil-1", "js-closure-3", "css-box-2"],
  created_at: "2026-07-25T10:00:00Z",
  updated_at: "2026-07-25T10:00:00Z",
};

const SAMPLE_RESOLVED: ResolvedQuestion[] = [
  {
    id: "py-gil-1",
    prompt_md: "GIL?",
    tags: ["python"],
    difficulty: 2,
    time_limit_seconds: 20,
    source: "seed",
    status: "active",
    blocked: false,
  },
  {
    id: "js-closure-3",
    prompt_md: "Closure?",
    tags: ["javascript"],
    difficulty: 3,
    time_limit_seconds: 20,
    source: "seed",
    status: "active",
    blocked: false,
  },
  {
    id: "css-box-2",
    prompt_md: "Box?",
    tags: ["css"],
    difficulty: 4,
    time_limit_seconds: 20,
    source: "seed",
    status: "active",
    blocked: false,
  },
];

function makeJob(overrides: Partial<JobOut>): JobOut {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    slug: "senior-frontend-engineer",
    title: "Senior Frontend Engineer",
    description_md: "",
    location: "Remote — Europe",
    remote_policy: "remote",
    employment_type: "full_time",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: "year",
    closes_at: null,
    tags: ["react", "typescript"],
    status: "published",
    quiz_config: {
      enabled: true,
      tags: null,
      question_count: 12,
      include_company_questions: true,
      time_limit_seconds: 25,
      difficulties: [2, 3],
      exclude_ids: [],
      questionnaire_id: null,
    },
    published_at: "2026-07-10T00:00:00Z",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("JobForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedQnr.list.mockResolvedValue([]);
    mockedQ.resolve.mockResolvedValue([]);
  });

  it("renders fields with defaults and assessment collapsed", () => {
    render(<JobForm submitLabel="Create job" onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("Job title")).toBeRequired();
    expect(screen.getByLabelText("Remote policy")).toHaveValue("onsite");
    expect(screen.getByLabelText("Employment type")).toHaveValue("full_time");
    expect(screen.getByRole("switch", { name: "Skills assessment" })).not.toBeChecked();
    expect(screen.queryByLabelText("Questions")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create job" })).toBeInTheDocument();
  });

  it("adds and removes tags via the chip input", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Job title"), "Backend Dev");
    const tagInput = screen.getByPlaceholderText("Add tag…");
    await userEvent.type(tagInput, "Python{Enter}FastAPI,backend{Enter}python{Enter}");
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("fastapi")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Remove tag backend" }));
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Backend Dev", tags: ["python", "fastapi"] }),
    );
  });

  it("submits salary period and the closes-on date", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Job title"), "Backend Dev");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "month");
    await userEvent.type(screen.getByLabelText(/Closes on/), "2026-12-01");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ salary_period: "month", closes_at: "2026-12-01" }),
    );
  });

  it("defaults to a yearly salary and no deadline", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Job title"), "Backend Dev");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ salary_period: "year", closes_at: null }),
    );
  });

  it("submits assessment config from the right rail controls", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Job title"), "Backend Dev");
    await userEvent.click(screen.getByRole("switch", { name: "Skills assessment" }));
    await userEvent.click(screen.getByRole("button", { name: "25s" }));
    await userEvent.click(screen.getByRole("button", { name: "Difficulty 3" }));
    await userEvent.click(screen.getByRole("button", { name: "Difficulty 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        quiz_config: {
          enabled: true,
          tags: null,
          question_count: 6,
          include_company_questions: true,
          time_limit_seconds: 25,
          difficulties: [2, 3],
          exclude_ids: [],
          questionnaire_id: null,
        },
      }),
    );
  });

  it("prefills from an existing job, incl. non-preset timer and slug", () => {
    render(
      <JobForm
        initial={makeJob({
          quiz_config: {
            enabled: true,
            tags: null,
            question_count: 12,
            include_company_questions: true,
            time_limit_seconds: 45,
            difficulties: null,
            exclude_ids: [],
            questionnaire_id: null,
          },
        })}
        submitLabel="Save changes"
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("URL slug")).toHaveValue("senior-frontend-engineer");
    expect(screen.getByText("react")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Skills assessment" })).toBeChecked();
    // legacy 45s value gets its own selected segment next to the presets
    expect(screen.getByRole("button", { name: "45s" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "20s" })).toHaveAttribute("aria-pressed", "false");
  });

  it("wraps the description selection via the markdown toolbar", async () => {
    render(<JobForm submitLabel="Create job" onSubmit={vi.fn()} />);
    const textarea = screen.getByLabelText("Description");
    await userEvent.click(screen.getByRole("button", { name: "Bold" }));
    expect(textarea).toHaveValue("**bold**");
  });

  it("renders extra rail content", () => {
    render(<JobForm submitLabel="Save" onSubmit={vi.fn()} rail={<div>Status card</div>} />);
    expect(screen.getByText("Status card")).toBeInTheDocument();
  });

  it("attaching a questionnaire hides tag-auto controls and submits questionnaire_id", async () => {
    mockedQnr.list.mockResolvedValue([SAMPLE_QUESTIONNAIRE]);
    mockedQ.resolve.mockResolvedValue(SAMPLE_RESOLVED);
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Job title"), "Frontend Dev");
    await userEvent.click(screen.getByRole("switch", { name: "Skills assessment" }));

    const picker = await screen.findByLabelText("Attach questionnaire");
    await userEvent.selectOptions(picker, "qnr-1");

    // attached summary appears; tag-auto controls disappear
    await waitFor(() =>
      expect(screen.getAllByText("Frontend basics v2").length).toBeGreaterThan(0),
    );
    expect(screen.queryByLabelText("Questions")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Question tags/)).not.toBeInTheDocument();
    // mix bar summary from the resolved questions
    expect(
      screen.getByText(/3 questions · 1 easy · 1 medium · 1 hard/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create job" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        quiz_config: expect.objectContaining({ questionnaire_id: "qnr-1" }),
      }),
    );
  });

  it("detach clears the attach and brings tag-auto controls back", async () => {
    mockedQnr.list.mockResolvedValue([SAMPLE_QUESTIONNAIRE]);
    mockedQ.resolve.mockResolvedValue(SAMPLE_RESOLVED);
    render(
      <JobForm
        initial={makeJob({
          quiz_config: {
            enabled: true,
            tags: null,
            question_count: 6,
            include_company_questions: true,
            time_limit_seconds: 25,
            difficulties: null,
            exclude_ids: [],
            questionnaire_id: "qnr-1",
          },
        })}
        submitLabel="Save changes"
        onSubmit={vi.fn()}
      />,
    );

    await screen.findByRole("button", { name: "Detach" });
    expect(screen.queryByLabelText("Questions")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Detach" }));
    expect(await screen.findByLabelText("Questions")).toBeInTheDocument();
    expect(screen.getByLabelText(/Question tags/)).toBeInTheDocument();
  });
});
