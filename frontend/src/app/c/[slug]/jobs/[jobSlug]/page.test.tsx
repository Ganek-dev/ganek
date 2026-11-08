import { beforeEach, describe, expect, it, vi } from "vitest";

const { companyPage, companyJob, resolveJobView, fetchInstanceInfo } = vi.hoisted(() => ({
  companyPage: vi.fn(),
  companyJob: vi.fn(),
  resolveJobView: vi.fn(),
  fetchInstanceInfo: vi.fn(),
}));

vi.mock("@/lib/public-api", () => ({
  publicApi: { companyPage, companyJob },
  resolveJobView,
  fetchInstanceInfo,
  demoRobots: (demo: boolean) => (demo ? { robots: { index: false, follow: false } } : {}),
}));
vi.mock("next/headers", () => ({ headers: vi.fn(), cookies: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));

import { generateMetadata } from "./page";

const job = {
  slug: "backend-engineer-python",
  title: "Backend Engineer (Python)",
  location: "Berlin",
  remote_policy: "onsite",
  employment_type: "full_time",
  salary_min: 65000,
  salary_max: 85000,
  salary_currency: "EUR",
  salary_period: "year",
  tags: [],
  published_at: null,
  closes_at: null,
  description_md: "## About the role\n\nYou own the services behind our fleet telemetry.\n",
};

describe("company job page metadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    companyPage.mockResolvedValue({
      company: { slug: "acme", name: "ACME Ganek", description: "Fictional demo company." },
      jobs: [],
    });
    resolveJobView.mockResolvedValue({ job, previewing: false });
    fetchInstanceInfo.mockResolvedValue({ mode: "multi", demo: false });
  });

  it("describes the job, not the platform, for search and share previews", async () => {
    const meta = await generateMetadata({
      params: Promise.resolve({ slug: "acme", jobSlug: "backend-engineer-python" }),
      searchParams: Promise.resolve({}),
    });
    expect(meta.title).toBe("Backend Engineer (Python) - ACME Ganek");
    expect(meta.description).toBe(
      "You own the services behind our fleet telemetry. Berlin · On-site · Full-time · 65,000-85,000 EUR/yr",
    );
  });

  it("names the custom domain as the canonical URL once verified", async () => {
    companyPage.mockResolvedValue({
      company: { slug: "acme", name: "ACME Ganek", careers_url: "https://careers.acme.com" },
      jobs: [],
    });
    const meta = await generateMetadata({
      params: Promise.resolve({ slug: "acme", jobSlug: "backend-engineer-python" }),
      searchParams: Promise.resolve({}),
    });
    expect(meta.alternates?.canonical).toBe(
      "https://careers.acme.com/jobs/backend-engineer-python",
    );
  });

  it("gives a preview no canonical URL", async () => {
    companyPage.mockResolvedValue({
      company: { slug: "acme", name: "ACME Ganek", careers_url: "https://careers.acme.com" },
      jobs: [],
    });
    resolveJobView.mockResolvedValue({ job, previewing: true });
    const meta = await generateMetadata({
      params: Promise.resolve({ slug: "acme", jobSlug: "backend-engineer-python" }),
      searchParams: Promise.resolve({ preview: "tok" }),
    });
    expect(meta.alternates).toBeUndefined();
    expect(meta.robots).toEqual({ index: false, follow: false });
  });

  it("returns nothing for an unknown job", async () => {
    resolveJobView.mockResolvedValue({ job: null, previewing: false });
    const meta = await generateMetadata({
      params: Promise.resolve({ slug: "acme", jobSlug: "nope" }),
      searchParams: Promise.resolve({}),
    });
    expect(meta).toEqual({});
  });
});
