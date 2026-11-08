import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PublicCompany, PublicJobDetail } from "@/lib/public-api";

import { ApplyNote, HowWeHire, JobGone, JobHero, JobPosting } from "./JobPosting";

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
  screening_questions: [],
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
  description_md: "Intro paragraph.\n\n## What you'll do\n\n- Ship `FastAPI` services\n- Review code",
  closes_at: null,
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
    for (const chip of ["Warsaw", "Hybrid", "Full-time", "15,000-25,000 PLN/yr"]) {
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

  it("derives the apply step from the same form config as the apply form", () => {
    render(
      <HowWeHire
        screeningQuestions={[
          { id: "q1", type: "yes_no", prompt: "Right to work?", options: null, required: true },
        ]}
      />,
    );
    expect(screen.getByText("Apply - four fields, about three minutes")).toBeInTheDocument();
  });

  it("drops the CV field on the demo", () => {
    render(<HowWeHire demo />);
    expect(screen.getByText("Apply - two fields, about one minute")).toBeInTheDocument();
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

  it("never renders markdown images - a remote img would leak visitor IPs", () => {
    const tracked: PublicJobDetail = {
      ...job,
      description_md:
        "Before.\n\n![our office](https://tracker.example/pixel.png)\n\nAfter.",
    };
    const { container } = render(<JobPosting company={company} job={tracked} />);
    expect(container.querySelector("img")).toBeNull();
    // alt text survives as plain text; surrounding content is untouched
    expect(screen.getByText("our office")).toBeInTheDocument();
    expect(screen.getByText("Before.")).toBeInTheDocument();
    expect(screen.getByText("After.")).toBeInTheDocument();
  });

  it("drops alt-less images entirely", () => {
    const tracked: PublicJobDetail = {
      ...job,
      description_md: "Text.\n\n![](https://tracker.example/pixel.png)",
    };
    const { container } = render(<JobPosting company={company} job={tracked} />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("omits the JSON-LD on a demo instance so fictional jobs never reach Google", () => {
    const { container } = render(<JobPosting company={company} job={job} jsonLd={false} />);
    expect(container.querySelector('script[type="application/ld+json"]')).toBeNull();
    expect(container.querySelector(".job-body")).not.toBeNull();
  });

  it("escapes '<' in the JSON-LD script so content can't break out of it", () => {
    const evil: PublicCompany = { ...company, name: "Acme </script><script>alert(1)" };
    const { container } = render(<JobPosting company={evil} job={job} />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    expect(script!.innerHTML).not.toContain("</script");
    expect(JSON.parse(script!.innerHTML)).toMatchObject({
      hiringOrganization: { name: "Acme </script><script>alert(1)" },
    });
  });
});

describe("Ganek attribution on job pages (BM10)", () => {
  it("shows the badge under the apply button on Free", () => {
    render(<ApplyNote poweredBy="badge" />);
    expect(screen.getByText("No account needed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Powered by Ganek" })).toHaveAttribute(
      "href",
      "https://ganek.io",
    );
  });

  it("keeps the inline credit on self-host and drops it on paid plans", () => {
    const { unmount } = render(<ApplyNote poweredBy="credit" />);
    expect(screen.getByText("No account needed · Careers powered by Ganek")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    unmount();
    render(<ApplyNote poweredBy="none" />);
    expect(screen.getByText("No account needed")).toBeInTheDocument();
    expect(screen.queryByText(/powered by ganek/i)).toBeNull();
  });

  it("carries the badge on the job-gone page of a Free company only", () => {
    const { unmount } = render(
      <JobGone company={{ ...company, powered_by: "badge" }} jobsHref="/" jobCount={0} />,
    );
    expect(screen.getByRole("link", { name: "Powered by Ganek" })).toBeInTheDocument();
    unmount();
    render(<JobGone company={{ ...company, powered_by: "none" }} jobsHref="/" jobCount={0} />);
    expect(screen.queryByText(/powered by ganek/i)).toBeNull();
  });
});
