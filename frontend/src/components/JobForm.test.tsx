import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  questionnaires,
  questions,
  team,
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
    team: { ...original.team, list: vi.fn() },
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
    screening_questions: [],
    id: "11111111-1111-1111-1111-111111111111",
    slug: "senior-frontend-engineer",
    title: "Senior Frontend Engineer",
    description_md: "",
    location: "Remote - Europe",
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
    closed_at: null,
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
    vi.mocked(team.list).mockResolvedValue([]);
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

  it("hints when the location contradicts the remote policy but still saves", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    const user = userEvent.setup();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Job title"), "SRE");
    await user.type(screen.getByLabelText("Location"), "Berlin or remote (EU)");
    expect(screen.getByRole("status")).toHaveTextContent("remote policy is On-site");
    await user.click(screen.getByRole("button", { name: "Create job" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      location: "Berlin or remote (EU)",
      remote_policy: "onsite",
    });
    await user.selectOptions(screen.getByLabelText("Remote policy"), "remote");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("blocks the save while a screening question would be refused and names the row", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    const user = userEvent.setup();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);
    await user.type(screen.getByLabelText("Job title"), "SRE");
    await user.click(screen.getByRole("button", { name: "Add question" }));
    await user.click(screen.getByRole("button", { name: "Create job" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert").map((el) => el.textContent)).toEqual([
      "Add a prompt",
      "Question 1: Add a prompt",
    ]);
    await user.type(screen.getByLabelText("Prompt"), "Can you work in Germany?");
    await user.click(screen.getByRole("button", { name: "Create job" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].screening_questions).toMatchObject([
      { prompt: "Can you work in Germany?" },
    ]);
  });

  it("hints on an existing job that already contradicts itself", () => {
    render(
      <JobForm
        submitLabel="Save"
        onSubmit={vi.fn()}
        initial={makeJob({ location: "Berlin, on-site", remote_policy: "remote" })}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("mentions on-site work");
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

describe("JobForm screening questions", () => {
  const PERMIT = {
    id: "sq_0000aa01",
    type: "yes_no" as const,
    prompt: "Can you work in Germany?",
    options: null,
    preferred: "yes",
    required: true,
  };

  it("submits the edited list", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("Job title"), "Backend Engineer");
    await userEvent.click(screen.getByRole("button", { name: "Add question" }));
    await userEvent.type(screen.getByLabelText("Prompt"), "Can you work in Germany?");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const values = onSubmit.mock.calls[0]![0];
    expect(values.screening_questions).toHaveLength(1);
    expect(values.screening_questions[0]).toMatchObject({
      type: "yes_no",
      prompt: "Can you work in Germany?",
      required: false,
    });
  });

  it("starts a new job from the company defaults and can reset to them", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} defaultScreening={[PERMIT]} />);
    expect(screen.getByLabelText("Prompt")).toHaveValue("Can you work in Germany?");
    await userEvent.click(screen.getByRole("button", { name: "Remove question 1" }));
    expect(screen.queryByLabelText("Prompt")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reset to company defaults" }));
    expect(screen.getByLabelText("Prompt")).toHaveValue("Can you work in Germany?");
  });

  it("prefills from the existing job, not from the company defaults", () => {
    render(
      <JobForm
        initial={makeJob({ screening_questions: [{ ...PERMIT, prompt: "Notice period?" }] })}
        submitLabel="Save changes"
        onSubmit={vi.fn()}
        defaultScreening={[PERMIT]}
      />,
    );
    expect(screen.getByLabelText("Prompt")).toHaveValue("Notice period?");
  });
});

describe("JobForm scorecard", () => {
  const CRIT = { id: "aaaaaaaa", label: "Problem solving", hint: "" };

  it("edits the job template and sends it back with saved ids intact", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(
      <JobForm
        initial={makeJob({ scorecard_template: [CRIT] })}
        submitLabel="Save changes"
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByRole("heading", { name: "Scorecard" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    await userEvent.type(screen.getAllByLabelText("Criterion label")[1]!, "Design");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0]![0].scorecard_template).toEqual([
      CRIT,
      { id: "", label: "Design", hint: "" },
    ]);
  });

  it("shows the empty hint on a job with no template", () => {
    render(<JobForm initial={makeJob({})} submitLabel="Save changes" onSubmit={vi.fn()} />);
    expect(
      screen.getByText(
        "Rate candidates against the criteria you add here. New jobs start from the company default in Settings.",
      ),
    ).toBeInTheDocument();
  });

  it("leaves the template out on create so the server copies the company default", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);
    expect(screen.queryByRole("heading", { name: "Scorecard" })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Job title"), "Backend Engineer");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0]![0]).not.toHaveProperty("scorecard_template");
  });
});

describe("JobForm blank scorecard label", () => {
  it("blocks the save with an inline message until the label is filled in", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm initial={makeJob({})} submitLabel="Save changes" onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Label is required")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Criterion label"), "Design");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  });
});

describe("JobForm job fields", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedQnr.list.mockResolvedValue([]);
    mockedQ.resolve.mockResolvedValue([]);
    vi.mocked(team.list).mockResolvedValue([
      {
        id: "user-ana",
        email: "ana@acme.test",
        display_label: "Ana",
        role: "admin",
        is_active: true,
        last_login_at: null,
        created_at: "2026-07-01T00:00:00Z",
      },
      {
        id: "user-gone",
        email: "gone@acme.test",
        display_label: "Gone",
        role: "member",
        is_active: false,
        last_login_at: null,
        created_at: "2026-07-01T00:00:00Z",
      },
    ]);
  });

  it("submits department, seniority, language, owner and the internal note", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Job title"), "Platform Engineer");
    await userEvent.type(screen.getByLabelText("Department"), "Infrastructure");
    await userEvent.selectOptions(screen.getByLabelText("Seniority"), "senior");
    await userEvent.selectOptions(screen.getByLabelText("Posting language"), "pl");
    await screen.findByRole("option", { name: "Ana" });
    // inactive teammates are not offered
    expect(screen.queryByRole("option", { name: "Gone" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/^Owner/), "user-ana");
    await userEvent.type(screen.getByLabelText(/^Internal note/), "Budget approved");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        department: "Infrastructure",
        seniority: "senior",
        language: "pl",
        owner_user_id: "user-ana",
        internal_note: "Budget approved",
        auto_close: false,
      }),
    );
  });

  it("sends nulls for unset fields", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("Job title"), "Backend Dev");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        department: "",
        seniority: null,
        language: null,
        owner_user_id: null,
        internal_note: "",
      }),
    );
  });

  it("offers auto-close only once a closes-on date is set", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);
    const toggle = screen.getByRole("checkbox", {
      name: "Close the job automatically after this day",
    });
    expect(toggle).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Job title"), "Backend Dev");
    await userEvent.type(screen.getByLabelText(/Closes on/), "2026-12-01");
    expect(toggle).toBeEnabled();
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ closes_at: "2026-12-01", auto_close: true }),
    );
  });

  it("keeps a stored owner and language that the pickers do not list", async () => {
    vi.mocked(team.list).mockRejectedValue(new Error("offline"));
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(
      <JobForm
        initial={makeJob({ owner_user_id: "user-x", language: "ja", department: "Data" })}
        submitLabel="Save changes"
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByLabelText("Department")).toHaveValue("Data");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ owner_user_id: "user-x", language: "ja", department: "Data" }),
      ),
    );
  });

  it("offers 45 and 60 second timers for longer questions", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText("Job title"), "Backend Dev");
    await userEvent.click(screen.getByRole("switch", { name: "Skills assessment" }));
    expect(screen.getByRole("button", { name: "45s" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "60s" }));
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        quiz_config: expect.objectContaining({ time_limit_seconds: 60 }),
      }),
    );
  });
});
