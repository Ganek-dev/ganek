import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, publicPages, type CompanySummary, type JobOut } from "@/lib/api";

import { GoogleJobsCard } from "./GoogleJobsCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, providers: vi.fn() },
    publicPages: { company: vi.fn(), job: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);
const mockedPublic = vi.mocked(publicPages);

const company: CompanySummary = { slug: "acme", name: "ACME Ganek", mode: "single" };

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    slug: "senior-frontend-engineer",
    title: "Senior Frontend Engineer",
    description_md: "## About the role\n\nReact on a fleet map.",
    location: "Berlin",
    remote_policy: "hybrid",
    employment_type: "full_time",
    salary_min: 75000,
    salary_max: 95000,
    salary_currency: "EUR",
    salary_period: "year",
    closes_at: "2026-12-31T00:00:00Z",
    tags: ["react"],
    status: "published",
    quiz_config: {
      enabled: false,
      tags: null,
      question_count: 10,
      include_company_questions: true,
      time_limit_seconds: 25,
      difficulties: null,
      questionnaire_id: null,
      exclude_ids: [],
    } as unknown as JobOut["quiz_config"],
    published_at: "2026-10-01T09:00:00Z",
    closed_at: null,
    created_at: "2026-09-20T09:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    ...overrides,
  };
}

const publicCompany = {
  slug: "acme",
  name: "ACME Ganek",
  description: "",
  logo_url: null,
  website: "https://acme.example",
  socials: {},
  theme: {},
};

/** The public job payload: the admin fields minus id, status and quiz config. */
function publicJobOf(job: JobOut) {
  return {
    slug: job.slug,
    title: job.title,
    location: job.location,
    remote_policy: job.remote_policy,
    employment_type: job.employment_type,
    salary_min: job.salary_min,
    salary_max: job.salary_max,
    salary_currency: job.salary_currency,
    salary_period: job.salary_period,
    tags: job.tags,
    published_at: job.published_at,
    description_md: job.description_md,
    closes_at: job.closes_at,
  };
}

describe("GoogleJobsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.providers.mockResolvedValue({ google: false, mode: "single", demo: false });
    mockedPublic.company.mockResolvedValue(publicCompany);
    mockedPublic.job.mockImplementation(async () => publicJobOf(makeJob()));
  });

  it("renders the markup the public page emits, the checks, a copy button and the docs link", async () => {
    render(<GoogleJobsCard job={makeJob()} company={company} urlFailed={false} />);
    expect(await screen.findByText("5 of 5 required fields present")).toBeInTheDocument();
    expect(screen.getByText("3 of 3 recommended")).toBeInTheDocument();
    const json = screen.getByTestId("google-jobs-json");
    expect(JSON.parse(json.textContent ?? "")).toMatchObject({
      "@type": "JobPosting",
      title: "Senior Frontend Engineer",
      hiringOrganization: { name: "ACME Ganek", sameAs: "https://acme.example" },
    });
    expect(screen.getByRole("button", { name: "Copy JSON-LD" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Docs" })).toHaveAttribute(
      "href",
      "https://ganek.dev/api-embed/#google-jobs-markup",
    );
    expect(mockedPublic.job).toHaveBeenCalledWith("single", "acme", "senior-frontend-engineer");
  });

  it("names the field to fix when a required one is missing", async () => {
    mockedPublic.job.mockImplementation(async () =>
      publicJobOf(makeJob({ location: "", remote_policy: "onsite" })),
    );
    render(<GoogleJobsCard job={makeJob()} company={company} urlFailed={false} />);
    expect(await screen.findByText("4 of 5 required fields present")).toBeInTheDocument();
    expect(screen.getByText(/Add a location/)).toBeInTheDocument();
  });

  it("says the markup is off on the demo and why, without fetching the public page", async () => {
    mockedApi.providers.mockResolvedValue({ google: false, mode: "single", demo: true });
    render(<GoogleJobsCard job={makeJob()} company={company} urlFailed={false} />);
    expect(await screen.findByText(/Off on the demo/)).toBeInTheDocument();
    expect(screen.getByText(/fictional/)).toBeInTheDocument();
    expect(screen.queryByTestId("google-jobs-json")).toBeNull();
    expect(mockedPublic.job).not.toHaveBeenCalled();
  });

  it("asks a draft to publish first and a closed job explains the removal", async () => {
    const { rerender } = render(
      <GoogleJobsCard
        job={makeJob({ status: "draft", published_at: null })}
        company={company}
        urlFailed={false}
      />,
    );
    expect(await screen.findByText("Appears once the job is published.")).toBeInTheDocument();
    rerender(
      <GoogleJobsCard
        job={makeJob({ status: "closed", closed_at: "2026-10-20T00:00:00Z" })}
        company={company}
        urlFailed={false}
      />,
    );
    expect(await screen.findByText("Removed when a job closes.")).toBeInTheDocument();
    expect(mockedPublic.job).not.toHaveBeenCalled();
  });

  it("explains when the public page cannot be loaded", async () => {
    mockedPublic.job.mockRejectedValue(new Error("boom"));
    render(<GoogleJobsCard job={makeJob()} company={company} urlFailed={false} />);
    expect(
      await screen.findByText("Could not load the public page for this job."),
    ).toBeInTheDocument();
  });

  it("waits for the company like the public link does", async () => {
    render(<GoogleJobsCard job={makeJob()} company={null} urlFailed />);
    expect(await screen.findByText("Markup loads with the company.")).toBeInTheDocument();
    await waitFor(() => expect(mockedPublic.job).not.toHaveBeenCalled());
  });
});
