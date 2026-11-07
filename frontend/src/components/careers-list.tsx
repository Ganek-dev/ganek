"use client";

import { useMemo, useState, useSyncExternalStore } from "react";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { jobMetaLine } from "@/components/careers";
import {
  EMPTY_CAREERS_FILTERS,
  type CareersFilters,
  type FilterOption,
  applyCareersFilters,
  careersFilterOptions,
  careersFiltersQuery,
  groupByDepartment,
  hasActiveFilters,
} from "@/lib/careers-filters";
import type { PublicJobSummary } from "@/lib/public-api";

/** Screen 01: filter row + bordered job cards with brand arrow, grouped by
 * department once the jobs span two or more.
 *
 * The filters are a plain GET form and the tag pills plain links, so the
 * SSR page filters without JS (the page parses the same query params and
 * passes them in as `initialFilters`). With JS the controls filter in place
 * and keep the URL in sync with history.replaceState - no server round trip.
 * Job links stay plain <a> for crawlers.
 */

const PILL_BASE =
  "inline-flex h-8 cursor-pointer items-center rounded-full px-3 text-[13px] pointer-coarse:h-11 pointer-coarse:px-4 sm:h-7";
const PILL_ACTIVE = `${PILL_BASE} bg-inverse font-medium text-inverse-foreground`;
const PILL_IDLE = `${PILL_BASE} border border-edge text-g700 hover:border-brand hover:text-brand`;
const CONTROL =
  "h-10 w-full rounded-md border-[1.5px] border-edge bg-transparent px-3 text-sm text-foreground focus:border-brand focus:outline-none pointer-coarse:h-11";

type SelectKey = "location" | "remote" | "type" | "dept";

const SELECTS: { key: SelectKey; label: string; all: string }[] = [
  { key: "dept", label: "Department", all: "All departments" },
  { key: "location", label: "Location", all: "All locations" },
  { key: "remote", label: "Work model", all: "Any work model" },
  { key: "type", label: "Employment type", all: "Any type" },
];

/** The current value stays selectable even when no open job carries it
 * (a shared link to a role that has since closed). */
function withCurrent(options: FilterOption[], current: string): FilterOption[] {
  if (!current || options.some((o) => o.value === current)) return options;
  return [...options, { value: current, label: current }];
}

const noSubscribe = () => () => {};
const isClient = () => true;
const isServer = () => false;

function JobCard({ job, href }: { job: PublicJobSummary; href: string }) {
  return (
    <li>
      <Link
        href={href}
        className="flex items-center justify-between gap-3 rounded-lg border border-edge px-4 py-[15px] hover:border-brand hover:shadow-[0_0_0_1px_var(--brand-primary)] sm:gap-4 sm:px-5 sm:py-[18px]"
      >
        <span className="flex flex-col gap-1">
          <span className="font-heading text-base font-medium sm:text-lg">{job.title}</span>
          <span className="font-mono text-[10.5px] text-g500 sm:text-[11.5px]">
            {jobMetaLine(job)}
          </span>
        </span>
        <ArrowRight aria-hidden className="h-[18px] w-[18px] shrink-0 text-brand" />
      </Link>
    </li>
  );
}

export function JobList({
  jobs,
  hrefPrefix,
  hrefSuffix = "",
  initialFilters = EMPTY_CAREERS_FILTERS,
}: {
  jobs: PublicJobSummary[];
  hrefPrefix: string;
  /** `?src=<bucket>` from the careers page so the job page keeps the source */
  hrefSuffix?: string;
  /** Filters parsed from the page's query params (SSR, works without JS). */
  initialFilters?: CareersFilters;
}) {
  const [filters, setFilters] = useState<CareersFilters>(initialFilters);
  // the submit button is only needed without JS: the controls apply live
  const enhanced = useSyncExternalStore(noSubscribe, isClient, isServer);

  const options = useMemo(() => careersFilterOptions(jobs), [jobs]);
  const src = useMemo(() => new URLSearchParams(hrefSuffix).get("src") ?? "", [hrefSuffix]);
  const extra = useMemo((): Record<string, string> => (src ? { src } : {}), [src]);

  if (jobs.length === 0) {
    return <p className="py-8 text-g500">No open positions right now - check back soon.</p>;
  }

  const update = (next: CareersFilters) => {
    setFilters(next);
    const query = careersFiltersQuery(next, extra);
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  };
  const hrefFor = (next: CareersFilters) => {
    const query = careersFiltersQuery(next, extra);
    return query ? `?${query}` : "?";
  };

  const visible = applyCareersFilters(jobs, filters);
  const groups = groupByDepartment(visible);
  const active = hasActiveFilters(filters);
  const selects = SELECTS.filter(({ key }) => options[key].length > 0 || filters[key]);
  const showSearch = options.search || filters.q !== "";
  const showForm = showSearch || selects.length > 0;
  const tagOptions = withCurrent(options.tag, filters.tag);
  const jobHref = (job: PublicJobSummary) => `${hrefPrefix}/${job.slug}${hrefSuffix}`;

  return (
    <div>
      {showForm ? (
        <form
          method="get"
          role="search"
          aria-label="Filter jobs"
          className="mb-3 flex flex-col gap-2 sm:mb-4 sm:flex-row sm:flex-wrap"
          onSubmit={(event) => {
            event.preventDefault();
            update(filters);
          }}
        >
          {src ? <input type="hidden" name="src" value={src} /> : null}
          {filters.tag ? <input type="hidden" name="tag" value={filters.tag} /> : null}
          {showSearch ? (
            <label className="sm:min-w-[220px] sm:flex-[2]">
              <span className="sr-only">Search jobs</span>
              <input
                type="search"
                name="q"
                value={filters.q}
                maxLength={100}
                placeholder="Search jobs"
                onChange={(event) => update({ ...filters, q: event.target.value })}
                className={CONTROL}
              />
            </label>
          ) : null}
          {selects.map(({ key, label, all }) => (
            <label key={key} className="sm:min-w-[150px] sm:flex-1">
              <span className="sr-only">{label}</span>
              <select
                name={key}
                value={filters[key]}
                onChange={(event) => update({ ...filters, [key]: event.target.value })}
                className={CONTROL}
              >
                <option value="">{all}</option>
                {withCurrent(options[key], filters[key]).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {enhanced ? null : (
            <button
              type="submit"
              className="h-10 rounded-md bg-inverse px-4 text-sm font-medium text-inverse-foreground pointer-coarse:h-11"
            >
              Filter
            </button>
          )}
        </form>
      ) : null}
      {tagOptions.length > 0 ? (
        <nav className="flex flex-wrap gap-1.5 sm:gap-2" aria-label="Filter by skill">
          {[{ value: "", label: "All" }, ...tagOptions].map((o) => {
            const next = { ...filters, tag: o.value };
            const current = filters.tag === o.value;
            return (
              <a
                key={o.value || "all"}
                href={hrefFor(next)}
                aria-current={current ? "true" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  update(next);
                }}
                className={current ? PILL_ACTIVE : PILL_IDLE}
              >
                {o.label}
              </a>
            );
          })}
        </nav>
      ) : null}
      <p className="mt-3 flex items-center gap-3 text-sm text-g500 empty:hidden" aria-live="polite">
        {active ? (
          <>
            <span>
              {visible.length} of {jobs.length} {jobs.length === 1 ? "position" : "positions"}
            </span>
            <a
              href={hrefFor(EMPTY_CAREERS_FILTERS)}
              onClick={(event) => {
                event.preventDefault();
                update(EMPTY_CAREERS_FILTERS);
              }}
              className="text-brand underline-offset-2 hover:underline"
            >
              Clear filters
            </a>
          </>
        ) : null}
      </p>
      {visible.length === 0 ? (
        <p className="py-8 text-sm text-g500">No positions match these filters.</p>
      ) : groups ? (
        <div className="mt-3.5 flex flex-col gap-6 sm:mt-5 sm:gap-8">
          {groups.map((group) => (
            <section
              key={group.department || "other"}
              aria-label={group.department || "Other roles"}
            >
              <h2 className="mb-2.5 font-mono text-[11px] tracking-wide text-g500 uppercase sm:mb-3">
                {group.department || "Other roles"}{" "}
                <span className="text-g400">({group.jobs.length})</span>
              </h2>
              <ul className="flex flex-col gap-2.5 sm:gap-3">
                {group.jobs.map((job) => (
                  <JobCard key={job.slug} job={job} href={jobHref(job)} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <ul className="mt-3.5 flex flex-col gap-2.5 sm:mt-5 sm:gap-3">
          {visible.map((job) => (
            <JobCard key={job.slug} job={job} href={jobHref(job)} />
          ))}
        </ul>
      )}
    </div>
  );
}
