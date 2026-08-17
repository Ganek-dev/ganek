import Link from "next/link";
import ReactMarkdown from "react-markdown";
import { ArrowLeft } from "lucide-react";

import {
  EMPLOYMENT_LABELS,
  REMOTE_LABELS,
  formatPostedAgo,
  formatSalary,
} from "@/components/careers";
import { mdToHtml } from "@/lib/md-html";
import type { PublicCompany, PublicJobDetail } from "@/lib/public-api";

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

export function jobPostingJsonLd(company: PublicCompany, job: PublicJobDetail): object {
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

/** Compact brand band for the job detail page (screen 02): logo chip + name,
 * back link, job title, meta chips on the brand color. */
export function JobHero({
  company,
  job,
  backHref,
}: {
  company: PublicCompany;
  job: PublicJobDetail;
  backHref: string;
}) {
  const chipStyle = {
    background: "color-mix(in oklab, var(--brand-primary-foreground) 16%, transparent)",
  };
  const chips = [
    job.location || null,
    REMOTE_LABELS[job.remote_policy],
    EMPLOYMENT_LABELS[job.employment_type],
    formatSalary(job),
  ].filter(Boolean) as string[];
  const postedAgo = formatPostedAgo(job.published_at);

  return (
    <header className="bg-brand text-brand-foreground">
      <div className="mx-auto max-w-[720px] px-5 pt-5 pb-7 sm:px-6 sm:pt-6 sm:pb-8">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            {company.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- remote host unknown at build time
              <img
                src={company.logo_url}
                alt=""
                className="h-[26px] w-[26px] rounded-sm bg-white object-contain"
              />
            ) : (
              <div
                aria-hidden
                className="flex h-[26px] w-[26px] items-center justify-center rounded-sm font-heading text-[14px] font-bold"
                style={chipStyle}
              >
                {company.name.charAt(0).toUpperCase()}
              </div>
            )}
            <span className="font-heading text-[16px] font-semibold">{company.name}</span>
          </div>
          <Link
            href={backHref}
            className="overline inline-flex items-center gap-1 opacity-80 hover:opacity-100"
          >
            <ArrowLeft aria-hidden className="h-3 w-3" strokeWidth={2.5} />
            All positions
          </Link>
        </div>
        <h1 className="mt-6 max-w-[560px] font-heading text-[26px] leading-[1.15] font-semibold tracking-[-0.01em] [text-wrap:pretty] sm:mt-7 sm:text-[34px] sm:leading-[1.12]">
          {job.title}
        </h1>
        <div className="mt-3.5 flex flex-wrap items-center gap-2">
          {chips.map((chip) => (
            <span
              key={chip}
              className="inline-flex h-6 items-center rounded-full px-2.5 font-mono text-[11.5px]"
              style={chipStyle}
            >
              {chip}
            </span>
          ))}
          {postedAgo ? (
            <span className="font-mono text-[11.5px] opacity-80">Posted {postedAgo}</span>
          ) : null}
        </div>
      </div>
    </header>
  );
}

/** Numbered hiring-steps card (screen 02). Copy stays platform-generic —
 * quiz settings are per-job and not exposed on the public API. */
export function HowWeHire() {
  const steps = [
    "Apply — three fields, about two minutes",
    "A short skills assessment for most roles — timed, one shot",
    "Interviews with the team",
  ];
  return (
    <section className="mt-8 rounded-lg border border-edge p-5">
      <h2 className="overline text-g500">How we hire</h2>
      <ol className="mt-2.5 space-y-2">
        {steps.map((step, index) => (
          <li
            key={step}
            className="flex items-center gap-2.5 text-sm leading-[21px] text-g700"
          >
            <span className="font-mono text-xs font-semibold text-brand">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span>{step}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Screen 27a — the posting is gone but the company still exists. Rendered
 * inside the company theme, with a way back to the open positions. */
export function JobGone({
  company,
  jobsHref,
  jobCount,
}: {
  company: PublicCompany;
  jobsHref: string;
  jobCount: number;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-surface text-foreground">
      <div className="border-b border-edge">
        <div className="mx-auto flex h-[60px] max-w-[720px] items-center gap-2.5 px-5 sm:px-6">
          <div
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-[7px] bg-brand font-heading text-[13px] font-bold text-brand-foreground"
          >
            {company.name.charAt(0).toUpperCase()}
          </div>
          <span className="font-heading text-[16px] font-semibold">{company.name}</span>
        </div>
      </div>
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="max-w-[380px] text-center">
          <div className="font-mono text-xs tracking-[0.08em] text-brand">404</div>
          <h1 className="mt-3 font-heading text-[25px] leading-[1.2] font-semibold">
            This role is gone
          </h1>
          <p className="mt-2.5 text-[14.5px] leading-[22px] text-g600 [text-wrap:pretty]">
            The posting was filled or taken down.
            {jobCount > 0
              ? ` ${company.name} has ${jobCount} other open position${
                  jobCount === 1 ? "" : "s"
                } right now.`
              : ""}
          </p>
          <Link
            href={jobsHref}
            className="mt-[22px] inline-flex h-[42px] items-center rounded-md bg-brand px-5 text-sm font-semibold text-brand-foreground hover:brightness-[0.94]"
          >
            See open positions
          </Link>
        </div>
      </div>
      <div className="flex h-11 shrink-0 items-center justify-center">
        <span className="font-mono text-[10.5px] text-g400">Careers powered by vetd</span>
      </div>
    </div>
  );
}

/** Recruiter markdown must not load remote images: an external <img> is a
 * tracking pixel leaking each candidate visitor's IP/UA to the image host
 * (GDPR G4). Alt text renders in its place. */
const jobMd = {
  img: ({ alt }: { alt?: string }) => (alt ? <span>{alt}</span> : null),
};

/** Editorial job description (screen 02): JSON-LD + markdown body. */
export function JobPosting({
  company,
  job,
}: {
  company: PublicCompany;
  job: PublicJobDetail;
}) {
  return (
    <article>
      <script
        type="application/ld+json"
        // '<' must not survive verbatim: a description containing
        // "</script>" would otherwise break out of this element
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(jobPostingJsonLd(company, job)).replaceAll("<", "\\u003c"),
        }}
      />
      <div className="job-body">
        <ReactMarkdown components={jobMd}>{job.description_md}</ReactMarkdown>
      </div>
    </article>
  );
}
