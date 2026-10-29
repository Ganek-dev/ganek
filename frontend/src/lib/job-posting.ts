import { mdToHtml } from "@/lib/md-html";
import type { PublicCompany, PublicJobDetail } from "@/lib/public-api";

/** schema.org JobPosting for a published job: what the public job page
 * emits as JSON-LD, and what the admin's "Google Jobs markup" card shows.
 * Pure: the page and the card build the same object from the same public
 * payloads. */

export type JobPostingJsonLd = Record<string, unknown>;

const EMPLOYMENT_TYPE_SCHEMA: Record<string, string> = {
  full_time: "FULL_TIME",
  part_time: "PART_TIME",
  contract: "CONTRACTOR",
  internship: "INTERN",
};

const SALARY_UNIT_SCHEMA: Record<string, string> = {
  hour: "HOUR",
  day: "DAY",
  week: "WEEK",
  month: "MONTH",
  year: "YEAR",
};

export function jobPostingJsonLd(company: PublicCompany, job: PublicJobDetail): JobPostingJsonLd {
  return {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    // Google wants an HTML description, not raw markdown
    description: mdToHtml(job.description_md),
    datePosted: job.published_at,
    ...(job.closes_at ? { validThrough: job.closes_at } : {}),
    employmentType: EMPLOYMENT_TYPE_SCHEMA[job.employment_type],
    hiringOrganization: {
      "@type": "Organization",
      name: company.name,
      ...(company.website ? { sameAs: company.website } : {}),
      ...(company.logo_url ? { logo: company.logo_url } : {}),
    },
    ...(job.location
      ? {
          jobLocation: {
            "@type": "Place",
            address: { "@type": "PostalAddress", addressLocality: job.location },
          },
        }
      : {}),
    ...(job.remote_policy === "remote" ? { jobLocationType: "TELECOMMUTE" } : {}),
    ...(job.salary_min !== null && job.salary_currency
      ? {
          baseSalary: {
            "@type": "MonetaryAmount",
            currency: job.salary_currency,
            value: {
              "@type": "QuantitativeValue",
              minValue: job.salary_min,
              ...(job.salary_max !== null ? { maxValue: job.salary_max } : {}),
              unitText: SALARY_UNIT_SCHEMA[job.salary_period] ?? "YEAR",
            },
          },
        }
      : {}),
  };
}

export interface JobPostingCheck {
  /** the JobPosting property, as Google's documentation names it */
  field: string;
  ok: boolean;
  /** required by Google for the posting to be eligible at all */
  required: boolean;
  /** what to change in Ganek when the check fails */
  hint: string;
}

function filled(value: unknown): boolean {
  return typeof value === "string" && value.trim() !== "";
}

/** Google's required properties (title, description, datePosted,
 * hiringOrganization, jobLocation or TELECOMMUTE) and the recommended
 * ones a recruiter can fill in. Visualization only: nothing blocks a
 * publish. */
export function jobPostingChecks(ld: JobPostingJsonLd): JobPostingCheck[] {
  const organization = ld.hiringOrganization as { name?: unknown } | undefined;
  return [
    { field: "title", required: true, ok: filled(ld.title), hint: "Give the job a title." },
    {
      field: "description",
      required: true,
      ok: filled(ld.description),
      hint: "Write the job description.",
    },
    {
      field: "datePosted",
      required: true,
      ok: filled(ld.datePosted),
      hint: "Set when the job is published.",
    },
    {
      field: "hiringOrganization",
      required: true,
      ok: filled(organization?.name),
      hint: "Set the company name under Settings.",
    },
    {
      field: "jobLocation",
      required: true,
      ok: ld.jobLocation !== undefined || ld.jobLocationType === "TELECOMMUTE",
      hint: "Add a location, or set the remote policy to Remote.",
    },
    {
      field: "employmentType",
      required: false,
      ok: filled(ld.employmentType),
      hint: "Pick an employment type.",
    },
    {
      field: "baseSalary",
      required: false,
      ok: ld.baseSalary !== undefined,
      hint: "Add a salary range: Google shows it in results.",
    },
    {
      field: "validThrough",
      required: false,
      ok: filled(ld.validThrough),
      hint: "Set Closes on so Google knows when the posting ends.",
    },
  ];
}
