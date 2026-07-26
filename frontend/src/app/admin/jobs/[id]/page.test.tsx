import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type JobOut } from "@/lib/api";

import EditJobPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ id: "11111111-1111-1111-1111-111111111111" }),
}));

vi.mock("@/components/QuizPreviewPanel", () => ({
  QuizPreviewPanel: () => <div>quiz preview</div>,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      jobs: { ...original.api.jobs, get: vi.fn(), publish: vi.fn(), close: vi.fn() },
    },
  };
});

const mockedJobs = vi.mocked(api.jobs);

function makeJob(overrides: Partial<JobOut>): JobOut {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    slug: "senior-frontend-engineer",
    title: "Senior Frontend Engineer",
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
    published_at: "2026-07-10T00:00:00Z",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("EditJobPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedJobs.get.mockResolvedValue(makeJob({}));
  });

  it("renders breadcrumb, status pill and the status card", async () => {
    render(<EditJobPage />);
    expect(
      await screen.findByRole("heading", { name: "Senior Frontend Engineer" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/senior-frontend-engineer/)).toBeInTheDocument();
    expect(screen.getAllByText("published").length).toBeGreaterThan(0);
    expect(screen.getByText(/Live since/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.getByText("quiz preview")).toBeInTheDocument();
  });

  it("closes a published job from the status card and reloads", async () => {
    mockedJobs.close.mockResolvedValue(makeJob({ status: "closed" }));
    render(<EditJobPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });

    mockedJobs.get.mockResolvedValue(makeJob({ status: "closed" }));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(mockedJobs.close).toHaveBeenCalledWith("11111111-1111-1111-1111-111111111111");
    expect(await screen.findByRole("button", { name: "Publish" })).toBeInTheDocument();
  });
});
