import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { PublicCompany, PublicJobDetail, PublicJobSummary } from "@/lib/public-api";

import { CompanyHero, formatPostedAgo, formatSalary, jobMetaLine } from "./careers";
import { JobList } from "./careers-list";
import { jobPostingJsonLd } from "./JobPosting";

const company: PublicCompany = {
  slug: "acme",
  name: "Acme",
  description: "We make anvils.",
  logo_url: null,
  website: "https://www.acme.test",
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
  salary_period: "year",
  tags: ["python", "fastapi"],
  published_at: "2026-07-21T12:00:00Z",
  description_md: "# Role\nBuild things.",
  closes_at: null,
};

const designJob: PublicJobSummary = {
  slug: "product-designer",
  title: "Product Designer",
  location: "London",
  remote_policy: "remote",
  employment_type: "full_time",
  salary_min: null,
  salary_max: null,
  salary_currency: null,
  salary_period: "year",
  tags: ["design"],
  published_at: null,
};

describe("careers hero", () => {
  it("renders the statement, company name, meta and website", () => {
    render(<CompanyHero company={company} jobCount={2} />);
    expect(screen.getByRole("heading", { name: "We make anvils." })).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("2 open positions")).toBeInTheDocument();
    const website = screen.getByRole("link", { name: /acme\.test/ });
    expect(website).toHaveAttribute("href", "https://www.acme.test");
    expect(website).toHaveTextContent("acme.test"); // hostname, www stripped
  });

  it("falls back to 'Careers at' when the description is empty", () => {
    render(<CompanyHero company={{ ...company, description: " " }} jobCount={1} />);
    expect(screen.getByRole("heading", { name: "Careers at Acme" })).toBeInTheDocument();
    expect(screen.getByText("1 open position")).toBeInTheDocument();
  });
});

describe("job list", () => {
  it("renders job cards with meta line and detail links", () => {
    render(<JobList jobs={[job]} hrefPrefix="/jobs" />);
    const link = screen.getByRole("link", { name: /Senior Python Developer/ });
    expect(link).toHaveAttribute("href", "/jobs/senior-python-developer");
    expect(link).toHaveTextContent(/Warsaw · Hybrid · Full-time · 15,000–25,000 PLN\/yr/);
  });

  it("shows the empty state without pills when there are no jobs", () => {
    render(<JobList jobs={[]} hrefPrefix="/jobs" />);
    expect(screen.getByText(/No open positions right now/)).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("filters by tag pill and resets via All", async () => {
    const user = userEvent.setup();
    render(<JobList jobs={[job, designJob]} hrefPrefix="/jobs" />);

    const pills = screen.getByRole("group", { name: "Filter jobs" });
    expect(pills).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "design" }));
    expect(screen.queryByRole("link", { name: /Senior Python Developer/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Product Designer/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "design" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("offers a Remote-only pill when remote and non-remote jobs mix", async () => {
    const user = userEvent.setup();
    render(<JobList jobs={[job, designJob]} hrefPrefix="/jobs" />);
    await user.click(screen.getByRole("button", { name: "Remote only" }));
    expect(screen.getByRole("link", { name: /Product Designer/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Senior Python Developer/ })).toBeNull();
  });

  it("hides the pill row for a single job", () => {
    render(<JobList jobs={[job]} hrefPrefix="/jobs" />);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });
});

describe("meta helpers", () => {
  it("formats salary bounds", () => {
    expect(formatSalary({ ...job, salary_max: null })).toBe("from 15,000 PLN/yr");
    expect(formatSalary({ ...job, salary_min: null, salary_max: null })).toBeNull();
  });

  it("formats posted-ago buckets", () => {
    const now = new Date("2026-07-24T12:00:00Z");
    expect(formatPostedAgo("2026-07-24T02:00:00Z", now)).toBe("today");
    expect(formatPostedAgo("2026-07-21T12:00:00Z", now)).toBe("3d ago");
    expect(formatPostedAgo("2026-07-07T12:00:00Z", now)).toBe("2w ago");
    expect(formatPostedAgo("2026-05-20T12:00:00Z", now)).toBe("2mo ago");
    expect(formatPostedAgo(null, now)).toBeNull();
    expect(formatPostedAgo("not-a-date", now)).toBeNull();
  });

  it("joins the meta line and skips missing parts", () => {
    const now = new Date("2026-07-24T12:00:00Z");
    expect(jobMetaLine(job, now)).toBe("Warsaw · Hybrid · Full-time · 15,000–25,000 PLN/yr · 3d ago");
    expect(jobMetaLine(designJob, now)).toBe("London · Remote · Full-time");
  });
});

describe("JSON-LD", () => {
  it("emits valid JobPosting JSON-LD", () => {
    const ld = jobPostingJsonLd(company, job) as Record<string, unknown>;
    expect(ld["@type"]).toBe("JobPosting");
    expect(ld.employmentType).toBe("FULL_TIME");
    expect(ld.hiringOrganization).toMatchObject({ name: "Acme" });
    expect(ld.baseSalary).toMatchObject({ currency: "PLN" });
  });

  it("renders the description as HTML, not raw markdown", () => {
    const ld = jobPostingJsonLd(company, job) as Record<string, unknown>;
    expect(ld.description).toContain("<h1>Role</h1>");
    expect(ld.description).not.toContain("# Role");
  });

  it("declares the salary unit from the job's period", () => {
    const yearly = jobPostingJsonLd(company, job) as { baseSalary: { value: object } };
    expect(yearly.baseSalary.value).toMatchObject({ unitText: "YEAR" });
    const monthly = jobPostingJsonLd(company, { ...job, salary_period: "month" }) as {
      baseSalary: { value: object };
    };
    expect(monthly.baseSalary.value).toMatchObject({ unitText: "MONTH" });
  });

  it("emits validThrough only when the job has a deadline", () => {
    expect(jobPostingJsonLd(company, job)).not.toHaveProperty("validThrough");
    const withDeadline = jobPostingJsonLd(company, {
      ...job,
      closes_at: "2026-12-01T00:00:00Z",
    }) as Record<string, unknown>;
    expect(withDeadline.validThrough).toBe("2026-12-01T00:00:00Z");
  });
});
