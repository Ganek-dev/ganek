"use client";

import { useMemo, useState } from "react";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { jobMetaLine } from "@/components/careers";
import type { PublicJobSummary } from "@/lib/public-api";

/** Screen 01: filter pill row + bordered job cards with brand arrow.
 * Client component for the pill filtering only — the initial list is still
 * server-rendered (SSR hard rule), and links stay plain <a> for crawlers.
 */

const MAX_TAG_FILTERS = 4;

interface JobFilter {
  key: string;
  label: string;
  matches: (job: PublicJobSummary) => boolean;
}

function buildFilters(jobs: PublicJobSummary[]): JobFilter[] {
  const filters: JobFilter[] = [{ key: "all", label: "All", matches: () => true }];
  if (jobs.length < 2) return filters;

  const counts = new Map<string, number>();
  for (const job of jobs) {
    for (const tag of job.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  const tags = [...counts.entries()]
    .filter(([, count]) => count < jobs.length) // a tag on every job filters nothing
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, MAX_TAG_FILTERS);
  for (const [tag] of tags) {
    filters.push({ key: `tag:${tag}`, label: tag, matches: (job) => job.tags.includes(tag) });
  }

  const remoteCount = jobs.filter((job) => job.remote_policy === "remote").length;
  if (remoteCount > 0 && remoteCount < jobs.length) {
    filters.push({
      key: "remote",
      label: "Remote only",
      matches: (job) => job.remote_policy === "remote",
    });
  }
  return filters;
}

const PILL_BASE =
  "inline-flex h-8 cursor-pointer items-center rounded-full px-3 text-[13px] sm:h-7";
const PILL_ACTIVE = `${PILL_BASE} bg-inverse font-medium text-inverse-foreground`;
const PILL_IDLE = `${PILL_BASE} border border-edge text-g700 hover:border-brand hover:text-brand`;

export function JobList({
  jobs,
  hrefPrefix,
}: {
  jobs: PublicJobSummary[];
  hrefPrefix: string;
}) {
  const [active, setActive] = useState("all");
  const filters = useMemo(() => buildFilters(jobs), [jobs]);

  if (jobs.length === 0) {
    return <p className="py-8 text-g500">No open positions right now — check back soon.</p>;
  }

  const filter = filters.find((f) => f.key === active) ?? filters[0];
  const visible = jobs.filter(filter.matches);

  return (
    <div>
      {filters.length > 1 ? (
        <div className="flex flex-wrap gap-1.5 sm:gap-2" role="group" aria-label="Filter jobs">
          {filters.map((f) => (
            <button
              key={f.key}
              type="button"
              aria-pressed={f.key === active}
              onClick={() => setActive(f.key)}
              className={f.key === active ? PILL_ACTIVE : PILL_IDLE}
            >
              {f.label}
            </button>
          ))}
        </div>
      ) : null}
      <ul className="mt-3.5 flex flex-col gap-2.5 sm:mt-5 sm:gap-3">
        {visible.map((job) => (
          <li key={job.slug}>
            <Link
              href={`${hrefPrefix}/${job.slug}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-edge px-4 py-[15px] hover:border-brand hover:shadow-[0_0_0_1px_var(--brand-primary)] sm:gap-4 sm:px-5 sm:py-[18px]"
            >
              <span className="flex flex-col gap-1">
                <span className="font-heading text-base font-medium sm:text-lg">
                  {job.title}
                </span>
                <span className="font-mono text-[10.5px] text-g500 sm:text-[11.5px]">
                  {jobMetaLine(job)}
                </span>
              </span>
              <ArrowRight aria-hidden className="h-[18px] w-[18px] shrink-0 text-brand" />
            </Link>
          </li>
        ))}
        {visible.length === 0 ? (
          <li className="py-8 text-sm text-g500">No positions match this filter.</li>
        ) : null}
      </ul>
    </div>
  );
}
