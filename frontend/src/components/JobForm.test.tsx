import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { JobInput, JobOut } from "@/lib/api";

import { JobForm } from "./JobForm";

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
    },
    published_at: "2026-07-10T00:00:00Z",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("JobForm", () => {
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
});
