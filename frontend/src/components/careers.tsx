import Link from "next/link";

import { brandStyle } from "@/lib/brand";
import type { PublicCompany, PublicJobSummary } from "@/lib/public-api";

const EMPLOYMENT_LABELS: Record<string, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  internship: "Internship",
};

const REMOTE_LABELS: Record<string, string> = {
  onsite: "On-site",
  hybrid: "Hybrid",
  remote: "Remote",
};

export function themeStyle(company: PublicCompany): React.CSSProperties {
  const theme = company.theme as { primary_color?: string };
  return brandStyle(theme.primary_color);
}

export function formatSalary(job: PublicJobSummary): string | null {
  if (job.salary_min === null && job.salary_max === null) return null;
  const currency = job.salary_currency ?? "";
  const fmt = (n: number) => n.toLocaleString("en-US");
  if (job.salary_min !== null && job.salary_max !== null) {
    return `${fmt(job.salary_min)}–${fmt(job.salary_max)} ${currency}`.trim();
  }
  const bound = job.salary_min ?? job.salary_max;
  return bound === null ? null : `from ${fmt(bound)} ${currency}`.trim();
}

export function CompanyHero({ company }: { company: PublicCompany }) {
  return (
    <header className="space-y-3 border-b border-zinc-200 pb-8 dark:border-zinc-800">
      <div className="flex items-center gap-4">
        {company.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- remote host unknown at build time
          <img src={company.logo_url} alt="" className="h-12 w-12 rounded-lg object-contain" />
        ) : null}
        <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">
          Careers at {company.name}
        </h1>
      </div>
      {company.description ? (
        <p className="max-w-2xl text-zinc-600 dark:text-zinc-400">{company.description}</p>
      ) : null}
      {company.website ? (
        <a
          href={company.website}
          rel="noopener noreferrer"
          className="text-sm underline"
          style={{ color: "var(--brand-primary)" }}
        >
          {company.website}
        </a>
      ) : null}
    </header>
  );
}

export function JobList({
  jobs,
  hrefFor,
}: {
  jobs: PublicJobSummary[];
  hrefFor: (job: PublicJobSummary) => string;
}) {
  if (jobs.length === 0) {
    return <p className="py-8 text-zinc-500">No open positions right now — check back soon.</p>;
  }
  return (
    <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {jobs.map((job) => {
        const salary = formatSalary(job);
        return (
          <li key={job.slug} className="py-5">
            <Link
              href={hrefFor(job)}
              className="text-lg font-semibold text-zinc-900 hover:underline dark:text-zinc-50"
            >
              {job.title}
            </Link>
            <p className="mt-1 text-sm text-zinc-500">
              {[
                job.location || null,
                REMOTE_LABELS[job.remote_policy],
                EMPLOYMENT_LABELS[job.employment_type],
                salary,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {job.tags.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {job.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
