import ReactMarkdown from "react-markdown";

import type { PublicCompany, PublicJobDetail } from "@/lib/public-api";

const EMPLOYMENT_TYPE_SCHEMA: Record<string, string> = {
  full_time: "FULL_TIME",
  part_time: "PART_TIME",
  contract: "CONTRACTOR",
  internship: "INTERN",
};

export function jobPostingJsonLd(company: PublicCompany, job: PublicJobDetail): object {
  return {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    title: job.title,
    description: job.description_md,
    datePosted: job.published_at,
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
              unitText: "MONTH",
            },
          },
        }
      : {}),
  };
}

export function JobPosting({
  company,
  job,
  backHref,
}: {
  company: PublicCompany;
  job: PublicJobDetail;
  backHref: string;
}) {
  return (
    <article className="space-y-6">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jobPostingJsonLd(company, job)) }}
      />
      <div>
        <a href={backHref} className="text-sm text-zinc-500 hover:underline">
          ← All positions at {company.name}
        </a>
        <h1 className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{job.title}</h1>
      </div>
      <div className="prose prose-zinc max-w-2xl dark:prose-invert">
        <ReactMarkdown>{job.description_md}</ReactMarkdown>
      </div>
    </article>
  );
}
