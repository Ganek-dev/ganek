import { describe, expect, it } from "vitest";

import type { PublicCompany, PublicJobDetail } from "@/lib/public-api";

import { jobPostingChecks, jobPostingJsonLd } from "./job-posting";

const company: PublicCompany = {
  slug: "acme",
  name: "ACME Ganek",
  description: "Fleet software.",
  logo_url: "https://acme.example/logo.png",
  website: "https://acme.example",
  socials: {},
  theme: {},
};

const job: PublicJobDetail = {
  screening_questions: [],
  slug: "senior-frontend-engineer",
  title: "Senior Frontend Engineer",
  location: "Berlin",
  remote_policy: "hybrid",
  employment_type: "full_time",
  salary_min: 75000,
  salary_max: 95000,
  salary_currency: "EUR",
  salary_period: "year",
  tags: ["react"],
  published_at: "2026-10-01T09:00:00Z",
  description_md: "## About the role\n\nReact and TypeScript on a fleet map.",
  closes_at: "2026-12-31T00:00:00Z",
};

describe("jobPostingJsonLd", () => {
  it("emits every field Google requires for a sample job", () => {
    const ld = jobPostingJsonLd(company, job);
    expect(ld).toMatchObject({
      "@context": "https://schema.org",
      "@type": "JobPosting",
      title: "Senior Frontend Engineer",
      datePosted: "2026-10-01T09:00:00Z",
      validThrough: "2026-12-31T00:00:00Z",
      employmentType: "FULL_TIME",
      hiringOrganization: {
        "@type": "Organization",
        name: "ACME Ganek",
        sameAs: "https://acme.example",
        logo: "https://acme.example/logo.png",
      },
      jobLocation: { address: { addressLocality: "Berlin" } },
      baseSalary: { currency: "EUR", value: { minValue: 75000, maxValue: 95000, unitText: "YEAR" } },
    });
    // Google wants HTML, not markdown
    expect(ld.description).toBe(
      "<h2>About the role</h2>\n<p>React and TypeScript on a fleet map.</p>",
    );
  });

  it("marks a remote job as TELECOMMUTE instead of a place", () => {
    const ld = jobPostingJsonLd(company, { ...job, location: "", remote_policy: "remote" });
    expect(ld.jobLocationType).toBe("TELECOMMUTE");
    expect(ld.jobLocation).toBeUndefined();
  });
});

describe("jobPostingChecks", () => {
  it("passes every required check for the sample job", () => {
    const checks = jobPostingChecks(jobPostingJsonLd(company, job));
    const required = checks.filter((check) => check.required);
    expect(required.map((check) => check.field)).toEqual([
      "title",
      "description",
      "datePosted",
      "hiringOrganization",
      "jobLocation",
    ]);
    expect(required.every((check) => check.ok)).toBe(true);
    expect(checks.filter((check) => !check.required).every((check) => check.ok)).toBe(true);
  });

  it("accepts TELECOMMUTE in place of a job location", () => {
    const checks = jobPostingChecks(
      jobPostingJsonLd(company, { ...job, location: "", remote_policy: "remote" }),
    );
    expect(checks.find((check) => check.field === "jobLocation")?.ok).toBe(true);
  });

  it("flags an on-site job without a location and the missing recommended fields", () => {
    const checks = jobPostingChecks(
      jobPostingJsonLd(company, {
        ...job,
        location: "",
        remote_policy: "onsite",
        salary_min: null,
        salary_max: null,
        salary_currency: null,
        closes_at: null,
      }),
    );
    const byField = Object.fromEntries(checks.map((check) => [check.field, check]));
    expect(byField.jobLocation.ok).toBe(false);
    expect(byField.jobLocation.required).toBe(true);
    expect(byField.jobLocation.hint).toMatch(/location/i);
    expect(byField.baseSalary.ok).toBe(false);
    expect(byField.baseSalary.required).toBe(false);
    expect(byField.validThrough.ok).toBe(false);
    expect(byField.employmentType.ok).toBe(true);
  });

  it("flags an empty description and a missing publish date", () => {
    const checks = jobPostingChecks(
      jobPostingJsonLd(company, { ...job, description_md: "", published_at: null }),
    );
    const byField = Object.fromEntries(checks.map((check) => [check.field, check]));
    expect(byField.description.ok).toBe(false);
    expect(byField.datePosted.ok).toBe(false);
  });
});
