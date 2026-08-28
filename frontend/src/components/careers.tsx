import Link from "next/link";

import { ArrowUpRight } from "lucide-react";

import { brandStyle } from "@/lib/brand";
import type { PublicCompany, PublicJobSummary } from "@/lib/public-api";

export const EMPLOYMENT_LABELS: Record<string, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  internship: "Internship",
};

export const REMOTE_LABELS: Record<string, string> = {
  onsite: "On-site",
  hybrid: "Hybrid",
  remote: "Remote",
};

export function themeStyle(company: PublicCompany): React.CSSProperties {
  const theme = company.theme as { primary_color?: string; radius?: string };
  return brandStyle(theme.primary_color, theme.radius);
}

const SALARY_PERIOD_LABELS: Record<string, string> = {
  hour: "/hr",
  day: "/day",
  week: "/wk",
  month: "/mo",
  year: "/yr",
};

export function formatSalary(job: PublicJobSummary): string | null {
  if (job.salary_min === null && job.salary_max === null) return null;
  const currency = job.salary_currency ?? "";
  const period = SALARY_PERIOD_LABELS[job.salary_period] ?? "";
  const fmt = (n: number) => n.toLocaleString("en-US");
  if (job.salary_min !== null && job.salary_max !== null) {
    return `${fmt(job.salary_min)}–${fmt(job.salary_max)} ${currency}${period}`.trim();
  }
  const bound = job.salary_min ?? job.salary_max;
  return bound === null ? null : `from ${fmt(bound)} ${currency}${period}`.trim();
}

/** Compact relative age for the job-card meta row ("2w ago"), per screen 01. */
export function formatPostedAgo(publishedAt: string | null, now: Date = new Date()): string | null {
  if (!publishedAt) return null;
  const posted = new Date(publishedAt);
  if (Number.isNaN(posted.getTime())) return null;
  const days = Math.floor((now.getTime() - posted.getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days < 7) return `${days}d ago`;
  if (days < 28) return `${Math.floor(days / 7)}w ago`;
  return `${Math.max(1, Math.floor(days / 30))}mo ago`;
}

/** Mono meta line under a job title: location · remote · type · salary · age. */
export function jobMetaLine(job: PublicJobSummary, now: Date = new Date()): string {
  return [
    job.location || null,
    REMOTE_LABELS[job.remote_policy],
    EMPLOYMENT_LABELS[job.employment_type],
    formatSalary(job),
    formatPostedAgo(job.published_at, now),
  ]
    .filter(Boolean)
    .join(" · ");
}

function websiteLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Brand-color hero band (screen 01 / 26a): logo chip, statement, mono meta. */
export function CompanyHero({
  company,
  jobCount,
}: {
  company: PublicCompany;
  jobCount: number;
}) {
  const statement = company.description.trim() || `Careers at ${company.name}`;
  return (
    <header className="bg-brand text-brand-foreground">
      <div className="mx-auto max-w-[720px] px-5 pt-5 pb-7 sm:px-6 sm:pt-7 sm:pb-10">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            {company.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- remote host unknown at build time
              <img
                src={company.logo_url}
                alt=""
                className="h-7 w-7 rounded-sm bg-white object-contain"
              />
            ) : (
              <div
                aria-hidden
                className="flex h-7 w-7 items-center justify-center rounded-sm font-heading text-[15px] font-bold"
                style={{
                  background:
                    "color-mix(in oklab, var(--brand-primary-foreground) 18%, transparent)",
                }}
              >
                {company.name.charAt(0).toUpperCase()}
              </div>
            )}
            <span className="font-heading text-[16px] font-semibold sm:text-[17px]">
              {company.name}
            </span>
          </div>
          {company.website ? (
            <a
              href={company.website}
              rel="noopener noreferrer"
              className="overline hidden items-center gap-1 opacity-75 hover:opacity-100 sm:inline-flex"
            >
              {websiteLabel(company.website)}
              <ArrowUpRight aria-hidden className="h-3 w-3" strokeWidth={2.5} />
            </a>
          ) : null}
        </div>
        <h1 className="mt-[22px] max-w-[560px] font-heading text-[26px] leading-[1.15] font-semibold tracking-[-0.01em] [text-wrap:pretty] sm:mt-9 sm:text-[38px] sm:leading-[1.12]">
          {statement}
        </h1>
        <p className="mt-2.5 font-mono text-[11px] opacity-85 sm:mt-4 sm:text-xs">
          {jobCount} open position{jobCount === 1 ? "" : "s"}
        </p>
      </div>
    </header>
  );
}

/** Quiet centered footer line closing the careers page (screen 01). */
export function CareersFooter({ privacyHref }: { privacyHref?: string }) {
  return (
    <div className="mt-7 flex justify-center gap-2 sm:mt-12">
      <span className="font-mono text-[10.5px] text-g400 sm:text-[11px]">
        Careers powered by ganek
      </span>
      {privacyHref ? (
        <>
          <span aria-hidden className="font-mono text-[10.5px] text-g400 sm:text-[11px]">
            ·
          </span>
          <Link
            href={privacyHref}
            className="font-mono text-[10.5px] text-g400 underline hover:text-g700 sm:text-[11px]"
          >
            Privacy
          </Link>
        </>
      ) : null}
    </div>
  );
}
