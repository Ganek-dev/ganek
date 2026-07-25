import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PublicCompany, PublicJobDetail } from "@/lib/public-api";

import { HowWeHire, JobGone, JobHero, JobPosting } from "./JobPosting";

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
  description_md: "Intro paragraph.\n\n## What you'll do\n\n- Ship `FastAPI` services\n- Review code",
};

describe("JobHero", () => {
  it("renders name, back link, title and meta chips", () => {
    render(<JobHero company={company} job={job} backHref="/c/acme" />);
    expect(screen.getByRole("heading", { name: "Senior Python Developer" })).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All positions/ })).toHaveAttribute(
      "href",
      "/c/acme",
    );
    for (const chip of ["Warsaw", "Hybrid", "Full-time", "15,000–25,000 PLN"]) {
      expect(screen.getByText(chip)).toBeInTheDocument();
    }
    expect(screen.getByText(/^Posted .+ ago$|^Posted today$/)).toBeInTheDocument();
  });

  it("omits the posted line when unpublished", () => {
    render(<JobHero company={company} job={{ ...job, published_at: null }} backHref="/" />);
    expect(screen.queryByText(/^Posted/)).toBeNull();
  });
});

describe("HowWeHire", () => {
  it("renders the three numbered steps", () => {
    render(<HowWeHire />);
    expect(screen.getByText("How we hire")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("01")).toBeInTheDocument();
    expect(screen.getByText(/three fields/)).toBeInTheDocument();
    expect(screen.getByText(/timed, one shot/)).toBeInTheDocument();
  });
});

describe("JobGone", () => {
  it("renders the 404 state with a link back to open positions", () => {
    render(<JobGone company={company} jobsHref="/c/acme" jobCount={3} />);
    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "This role is gone" })).toBeInTheDocument();
    expect(screen.getByText(/3 other open positions/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See open positions" })).toHaveAttribute(
      "href",
      "/c/acme",
    );
  });

  it("omits the open-positions count when there are none", () => {
    render(<JobGone company={company} jobsHref="/" jobCount={0} />);
    expect(screen.queryByText(/other open position/)).toBeNull();
  });
});

describe("JobPosting", () => {
  it("renders the markdown body with editorial elements", () => {
    render(<JobPosting company={company} job={job} />);
    expect(screen.getByText("Intro paragraph.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What you'll do" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("FastAPI").tagName).toBe("CODE");
  });
});
