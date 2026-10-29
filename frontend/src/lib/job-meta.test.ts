import { describe, expect, it } from "vitest";

import type { PublicCompany, PublicJobDetail } from "./public-api";
import { jobMetaDescription } from "./job-meta";

const company = {
  slug: "acme",
  name: "ACME Ganek",
  description: "Fictional demo company. ACME Ganek builds autonomous warehouse robots.",
} as PublicCompany;

function makeJob(overrides: Partial<PublicJobDetail> = {}): PublicJobDetail {
  return {
    slug: "backend-engineer-python",
    title: "Backend Engineer (Python)",
    location: "Berlin",
    remote_policy: "onsite",
    employment_type: "full_time",
    salary_min: 65000,
    salary_max: 85000,
    salary_currency: "EUR",
    salary_period: "year",
    tags: ["python"],
    published_at: "2026-10-01T00:00:00Z",
    closes_at: null,
    description_md:
      "## About the role\n\nYou own the services behind our fleet telemetry: FastAPI, PostgreSQL, a worker queue.\n\n## What we look for\n\n- Solid Python and SQL\n",
    ...overrides,
  };
}

describe("jobMetaDescription", () => {
  it("leads with the first paragraph, then location, remote policy, type and salary", () => {
    expect(jobMetaDescription(makeJob(), company)).toBe(
      "You own the services behind our fleet telemetry: FastAPI, PostgreSQL, a worker queue. " +
        "Berlin · On-site · Full-time · 65,000-85,000 EUR/yr",
    );
  });

  it("skips headings and takes the first real paragraph, with inline markdown stripped", () => {
    const job = makeJob({
      description_md:
        "# Title\n\n### Sub\n\nWe build **robots** with [FastAPI](https://fastapi.tiangolo.com) and `asyncio`, _fast_.\n\nSecond paragraph.",
    });
    expect(jobMetaDescription(job, company)).toMatch(
      /^We build robots with FastAPI and asyncio, fast\. Berlin/,
    );
  });

  it("falls back to the first list item when the description opens with a list", () => {
    const job = makeJob({ description_md: "- Ship the telemetry API\n- Be on call\n" });
    expect(jobMetaDescription(job, company)).toMatch(/^Ship the telemetry API\. Berlin/);
  });

  it("leaves out empty facts", () => {
    const job = makeJob({
      location: "",
      salary_min: null,
      salary_max: null,
      salary_currency: null,
      description_md: "Plain paragraph.",
    });
    expect(jobMetaDescription(job, company)).toBe("Plain paragraph. On-site · Full-time");
  });

  it("uses the facts alone when the description is empty", () => {
    const job = makeJob({ description_md: "" });
    expect(jobMetaDescription(job, company)).toBe(
      "Berlin · On-site · Full-time · 65,000-85,000 EUR/yr",
    );
  });

  it("falls back to the company description when the job carries nothing", () => {
    const job = makeJob({
      description_md: "## Only a heading",
      location: "",
      salary_min: null,
      salary_max: null,
      remote_policy: "" as PublicJobDetail["remote_policy"],
      employment_type: "" as PublicJobDetail["employment_type"],
    });
    expect(jobMetaDescription(job, company)).toBe(company.description);
  });

  it("keeps the whole thing within 200 characters, cutting the paragraph at a word", () => {
    const job = makeJob({ description_md: `${"word ".repeat(80)}end.` });
    const out = jobMetaDescription(job, company) ?? "";
    expect(out.length).toBeLessThanOrEqual(200);
    expect(out).toMatch(/^word (word )*word\.\.\. Berlin · On-site · Full-time · 65,000-85,000 EUR\/yr$/);
  });

  it("never contains an em or en dash", () => {
    const job = makeJob({ description_md: "Fast \u2014 reliable \u2013 shipped." });
    expect(jobMetaDescription(job, company)).not.toMatch(new RegExp("[\\u2013\\u2014]"));
  });
});
