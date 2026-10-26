import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, questionnaires, questions, type JobOut } from "@/lib/api";

import EditJobPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: "11111111-1111-1111-1111-111111111111" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      jobs: {
        ...original.api.jobs,
        get: vi.fn(),
        update: vi.fn(),
        publish: vi.fn(),
        close: vi.fn(),
      },
    },
    questionnaires: { ...original.questionnaires, list: vi.fn() },
    questions: { ...original.questions, resolve: vi.fn() },
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
    salary_period: "year",
    closes_at: null,
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
      questionnaire_id: null,
    },
    published_at: "2026-07-10T00:00:00Z",
    closed_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("EditJobPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedJobs.get.mockResolvedValue(makeJob({}));
    vi.mocked(questionnaires.list).mockResolvedValue([]);
    vi.mocked(questions.resolve).mockResolvedValue([]);
  });

  it("renders breadcrumb with the edit segment, status pill and the status card", async () => {
    render(<EditJobPage />);
    expect(
      await screen.findByRole("heading", { name: "Senior Frontend Engineer" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "senior-frontend-engineer" })).toHaveAttribute(
      "href",
      "/admin/jobs/11111111-1111-1111-1111-111111111111",
    );
    expect(screen.getByText(/\/ edit$/)).toBeInTheDocument();
    expect(screen.getAllByText("published").length).toBeGreaterThan(0);
    expect(screen.getByText(/Live since/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.queryByText("quiz preview")).not.toBeInTheDocument();
  });

  it("returns to the job overview after saving", async () => {
    mockedJobs.update.mockResolvedValue(makeJob({ title: "Staff Frontend Engineer" }));
    render(<EditJobPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(mockedJobs.update).toHaveBeenCalledWith(
      "11111111-1111-1111-1111-111111111111",
      expect.objectContaining({ title: "Senior Frontend Engineer" }),
    );
    expect(push).toHaveBeenCalledWith("/admin/jobs/11111111-1111-1111-1111-111111111111");
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
