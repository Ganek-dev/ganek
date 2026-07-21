import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PublicCompany, PublicJobDetail } from "@/lib/public-api";

import { formatSalary, CompanyHero, JobList } from "./careers";
import { jobPostingJsonLd } from "./JobPosting";

const company: PublicCompany = {
  slug: "acme",
  name: "Acme",
  description: "We make anvils.",
  logo_url: null,
  website: "https://acme.test",
  socials: {},
  theme: {},
};

const job: PublicJobDetail = {
  slug: "senior-python-developer",
  title: "Senior Python Developer",
  location: "Warsaw",
  remote_policy: "hybrid",
  employment_type: "full_time",
  salary_min: 15000,
  salary_max: 25000,
  salary_currency: "PLN",
  tags: ["python", "fastapi"],
  published_at: "2026-07-21T12:00:00Z",
  description_md: "# Role\nBuild things.",
};

describe("careers components", () => {
  it("renders hero and job list", () => {
    render(
      <div>
        <CompanyHero company={company} />
        <JobList jobs={[job]} hrefFor={(j) => `/jobs/${j.slug}`} />
      </div>,
    );
    expect(screen.getByRole("heading", { name: "Careers at Acme" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Senior Python Developer" });
    expect(link).toHaveAttribute("href", "/jobs/senior-python-developer");
    expect(screen.getByText(/15,000–25,000 PLN/)).toBeInTheDocument();
  });

  it("formats salary bounds", () => {
    expect(formatSalary({ ...job, salary_max: null })).toBe("from 15,000 PLN");
    expect(formatSalary({ ...job, salary_min: null, salary_max: null })).toBeNull();
  });

  it("emits valid JobPosting JSON-LD", () => {
    const ld = jobPostingJsonLd(company, job) as Record<string, unknown>;
    expect(ld["@type"]).toBe("JobPosting");
    expect(ld.employmentType).toBe("FULL_TIME");
    expect(ld.hiringOrganization).toMatchObject({ name: "Acme" });
    expect(ld.baseSalary).toMatchObject({ currency: "PLN" });
  });
});
