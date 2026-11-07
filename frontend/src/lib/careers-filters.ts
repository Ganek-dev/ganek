import { EMPLOYMENT_LABELS, REMOTE_LABELS } from "@/components/careers";
import type { PublicJobSummary } from "@/lib/public-api";

/** Careers page filters (card "Careers page: filters, search"). The state
 * lives in the query string so the SSR page filters without JS, a filtered
 * view is a shareable link, and the back button works. Defaults are omitted
 * so the plain careers URL stays clean. */

export interface CareersFilters {
  q: string;
  location: string;
  remote: string;
  type: string;
  dept: string;
  tag: string;
}

export const EMPTY_CAREERS_FILTERS: CareersFilters = {
  q: "",
  location: "",
  remote: "",
  type: "",
  dept: "",
  tag: "",
};

const FILTER_KEYS = ["q", "location", "remote", "type", "dept", "tag"] as const;
const MAX_PARAM_LENGTH = 100;
const MAX_TAG_FILTERS = 4;

type RawParams = Record<string, string | string[] | undefined>;

function firstValue(value: string | string[] | undefined): string {
  const raw = Array.isArray(value) ? value[0] : value;
  return (raw ?? "").trim().slice(0, MAX_PARAM_LENGTH);
}

/** Read the filters from page `searchParams` (or any plain record). */
export function parseCareersFilters(params: RawParams): CareersFilters {
  const out = { ...EMPTY_CAREERS_FILTERS };
  for (const key of FILTER_KEYS) out[key] = firstValue(params[key]);
  if (out.remote && !(out.remote in REMOTE_LABELS)) out.remote = "";
  if (out.type && !(out.type in EMPLOYMENT_LABELS)) out.type = "";
  return out;
}

/** Query string for a filter state, without the leading "?". Extra params
 * (the `src` source bucket) are kept first so job links stay attributed. */
export function careersFiltersQuery(
  filters: CareersFilters,
  extra: Record<string, string> = {},
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(extra)) if (value) params.set(key, value);
  for (const key of FILTER_KEYS) if (filters[key]) params.set(key, filters[key]);
  return params.toString();
}

export function hasActiveFilters(filters: CareersFilters): boolean {
  return FILTER_KEYS.some((key) => filters[key] !== "");
}

function fold(text: string): string {
  return text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Search matches every word against title, department, location and tags,
 * accent- and case-insensitive ("krakow" finds "Kraków"). */
function matchesSearch(job: PublicJobSummary, q: string): boolean {
  const words = fold(q).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = fold([job.title, job.department ?? "", job.location, ...job.tags].join(" "));
  return words.every((word) => haystack.includes(word));
}

export function applyCareersFilters(
  jobs: PublicJobSummary[],
  filters: CareersFilters,
): PublicJobSummary[] {
  return jobs.filter(
    (job) =>
      (!filters.location || job.location === filters.location) &&
      (!filters.remote || job.remote_policy === filters.remote) &&
      (!filters.type || job.employment_type === filters.type) &&
      (!filters.dept || (job.department ?? "") === filters.dept) &&
      (!filters.tag || job.tags.includes(filters.tag)) &&
      matchesSearch(job, filters.q),
  );
}

export interface FilterOption {
  value: string;
  label: string;
}

export interface CareersFilterOptions {
  location: FilterOption[];
  remote: FilterOption[];
  type: FilterOption[];
  dept: FilterOption[];
  tag: FilterOption[];
  /** Search pays off once the list no longer fits on one screen. */
  search: boolean;
}

const SEARCH_MIN_JOBS = 6;

function distinct(values: string[], label: (value: string) => string): FilterOption[] {
  const unique = [...new Set(values.filter(Boolean))];
  // one value filters nothing: no dropdown for it
  if (unique.length < 2) return [];
  return unique
    .map((value) => ({ value, label: label(value) }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** The filter controls a job list warrants. A dimension with a single value
 * (every job in Warsaw) gets no control, so a small page stays as quiet as
 * it was. Options come from the open jobs, so none of them leads to an
 * empty list on its own. */
export function careersFilterOptions(jobs: PublicJobSummary[]): CareersFilterOptions {
  const counts = new Map<string, number>();
  for (const job of jobs) {
    for (const tag of job.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  const tag =
    jobs.length < 2
      ? []
      : [...counts.entries()]
          .filter(([, count]) => count < jobs.length) // a tag on every job filters nothing
          .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
          .slice(0, MAX_TAG_FILTERS)
          .map(([value]) => ({ value, label: value }));
  return {
    location: distinct(
      jobs.map((job) => job.location),
      (value) => value,
    ),
    remote: distinct(
      jobs.map((job) => job.remote_policy),
      (value) => REMOTE_LABELS[value] ?? value,
    ),
    type: distinct(
      jobs.map((job) => job.employment_type),
      (value) => EMPLOYMENT_LABELS[value] ?? value,
    ),
    dept: distinct(
      jobs.map((job) => job.department ?? ""),
      (value) => value,
    ),
    tag,
    search: jobs.length >= SEARCH_MIN_JOBS,
  };
}

export interface DepartmentGroup {
  /** "" collects the jobs without a department, listed last. */
  department: string;
  jobs: PublicJobSummary[];
}

/** Group by department once the jobs span at least two departments; a
 * single group (or none) means a flat list. Order follows the first job of
 * each department, so the recruiter's job order still leads. */
export function groupByDepartment(jobs: PublicJobSummary[]): DepartmentGroup[] | null {
  const groups = new Map<string, PublicJobSummary[]>();
  for (const job of jobs) {
    const key = job.department || "";
    const list = groups.get(key);
    if (list) list.push(job);
    else groups.set(key, [job]);
  }
  const named = [...groups.keys()].filter(Boolean);
  if (named.length < 2) return null;
  const out = named.map((department) => ({
    department,
    jobs: groups.get(department)!,
  }));
  const rest = groups.get("");
  if (rest) out.push({ department: "", jobs: rest });
  return out;
}
