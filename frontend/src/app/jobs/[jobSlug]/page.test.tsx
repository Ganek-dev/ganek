import { beforeEach, describe, expect, it, vi } from "vitest";

const { singleCompanyPage, singleCompanyJob, resolveJobView, fetchInstanceInfo } = vi.hoisted(() => ({
  singleCompanyPage: vi.fn(),
  singleCompanyJob: vi.fn(),
  resolveJobView: vi.fn(),
  fetchInstanceInfo: vi.fn(),
}));

vi.mock("@/lib/public-api", () => ({
  publicApi: { singleCompanyPage, singleCompanyJob },
  resolveJobView,
  fetchInstanceInfo,
  demoRobots: (demo: boolean) => (demo ? { robots: { index: false, follow: false } } : {}),
}));
vi.mock("next/headers", () => ({ headers: vi.fn(), cookies: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));

import { generateMetadata } from "./page";

describe("single-mode job page metadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    singleCompanyPage.mockResolvedValue({
      company: { slug: "acme", name: "ACME Ganek", description: "Fictional demo company." },
      jobs: [],
    });
    resolveJobView.mockResolvedValue({
      job: {
        slug: "sre",
        title: "Site Reliability Engineer",
        location: "Berlin or remote (EU)",
        remote_policy: "remote",
        employment_type: "full_time",
        salary_min: null,
        salary_max: null,
        salary_currency: null,
        salary_period: "year",
        tags: [],
        published_at: null,
        closes_at: null,
        description_md: "Keep the fleet up.",
      },
      previewing: false,
    });
    fetchInstanceInfo.mockResolvedValue({ mode: "single", demo: false });
  });

  it("describes the job, not the platform", async () => {
    const meta = await generateMetadata({
      params: Promise.resolve({ jobSlug: "sre" }),
      searchParams: Promise.resolve({}),
    });
    expect(meta.title).toBe("Site Reliability Engineer - ACME Ganek");
    expect(meta.description).toBe("Keep the fleet up. Berlin or remote (EU) · Remote · Full-time");
  });
});
