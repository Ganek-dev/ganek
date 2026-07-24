import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type JobOut } from "@/lib/api";

import JobsPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, jobs: { ...original.api.jobs, list: vi.fn() } },
  };
});

const mockedJobs = vi.mocked(api.jobs);

function makeJob(overrides: Partial<JobOut>): JobOut {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    slug: "job",
    title: "Job",
    description_md: "",
    location: "",
    remote_policy: "remote",
    employment_type: "full_time",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    tags: [],
    status: "published",
    quiz_config: {
      enabled: false,
      tags: null,
      question_count: 6,
      include_company_questions: true,
      time_limit_seconds: 20,
      difficulties: null,
      exclude_ids: [],
    },
    published_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("JobsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedJobs.list.mockResolvedValue([
      makeJob({ id: "11111111-1111-1111-1111-111111111111", title: "Live role", status: "published" }),
      makeJob({ id: "22222222-2222-2222-2222-222222222222", title: "Old role", status: "closed" }),
    ]);
  });

  it("hides closed jobs by default and shows them on All", async () => {
    render(<JobsPage />);
    expect(await screen.findByText("Live role")).toBeInTheDocument();
    expect(screen.queryByText("Old role")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Old role")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Closed" }));
    expect(screen.queryByText("Live role")).not.toBeInTheDocument();
    expect(screen.getByText("Old role")).toBeInTheDocument();
  });
});
