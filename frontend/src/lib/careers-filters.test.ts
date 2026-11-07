import { describe, expect, it } from "vitest";

import {
  EMPTY_CAREERS_FILTERS,
  applyCareersFilters,
  careersFilterOptions,
  careersFiltersQuery,
  groupByDepartment,
  hasActiveFilters,
  parseCareersFilters,
} from "@/lib/careers-filters";
import type { PublicJobSummary } from "@/lib/public-api";

function makeJob(overrides: Partial<PublicJobSummary>): PublicJobSummary {
  return {
    slug: "job",
    title: "Job",
    location: "Warsaw",
    remote_policy: "onsite",
    employment_type: "full_time",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_period: "year",
    tags: [],
    published_at: null,
    department: "",
    ...overrides,
  };
}

const backend = makeJob({
  slug: "backend",
  title: "Backend Engineer",
  location: "Kraków",
  remote_policy: "hybrid",
  department: "Engineering",
  tags: ["python"],
});
const sre = makeJob({
  slug: "sre",
  title: "Site Reliability Engineer",
  location: "Berlin",
  remote_policy: "remote",
  department: "Engineering",
  tags: ["kubernetes", "python"],
});
const designer = makeJob({
  slug: "designer",
  title: "Product Designer",
  employment_type: "contract",
  department: "Design",
  tags: ["figma"],
});
const intern = makeJob({ slug: "intern", title: "Office Intern", employment_type: "internship" });
const jobs = [backend, sre, designer, intern];

describe("parseCareersFilters", () => {
  it("reads, trims and caps the known params", () => {
    const f = parseCareersFilters({
      q: "  python ",
      location: ["Berlin", "Warsaw"],
      dept: "x".repeat(300),
      utm_source: "ignored",
    });
    expect(f.q).toBe("python");
    expect(f.location).toBe("Berlin");
    expect(f.dept).toHaveLength(100);
    expect(f.tag).toBe("");
  });

  it("drops unknown enum values", () => {
    const f = parseCareersFilters({ remote: "moon", type: "gig" });
    expect(f.remote).toBe("");
    expect(f.type).toBe("");
    expect(parseCareersFilters({ remote: "remote", type: "contract" })).toMatchObject({
      remote: "remote",
      type: "contract",
    });
  });
});

describe("careersFiltersQuery", () => {
  it("omits defaults and keeps the source first", () => {
    expect(careersFiltersQuery(EMPTY_CAREERS_FILTERS)).toBe("");
    expect(
      careersFiltersQuery({ ...EMPTY_CAREERS_FILTERS, q: "a b", dept: "R&D" }, { src: "linkedin" }),
    ).toBe("src=linkedin&q=a+b&dept=R%26D");
    expect(hasActiveFilters(EMPTY_CAREERS_FILTERS)).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_CAREERS_FILTERS, tag: "python" })).toBe(true);
  });
});

describe("applyCareersFilters", () => {
  const run = (overrides: Partial<typeof EMPTY_CAREERS_FILTERS>) =>
    applyCareersFilters(jobs, { ...EMPTY_CAREERS_FILTERS, ...overrides }).map((j) => j.slug);

  it("passes everything with no filters", () => {
    expect(run({})).toEqual(["backend", "sre", "designer", "intern"]);
  });

  it("filters each dimension and combines them", () => {
    expect(run({ dept: "Engineering" })).toEqual(["backend", "sre"]);
    expect(run({ remote: "remote" })).toEqual(["sre"]);
    expect(run({ type: "contract" })).toEqual(["designer"]);
    expect(run({ location: "Warsaw" })).toEqual(["designer", "intern"]);
    expect(run({ tag: "python", remote: "hybrid" })).toEqual(["backend"]);
  });

  it("searches every word across title, department, location and tags", () => {
    expect(run({ q: "engineer" })).toEqual(["backend", "sre"]);
    expect(run({ q: "krakow" })).toEqual(["backend"]); // accent-insensitive
    expect(run({ q: "KUBERNETES berlin" })).toEqual(["sre"]);
    expect(run({ q: "design" })).toEqual(["designer"]);
    expect(run({ q: "rust" })).toEqual([]);
  });
});

describe("careersFilterOptions", () => {
  it("offers a control only for dimensions with two or more values", () => {
    const options = careersFilterOptions(jobs);
    expect(options.location.map((o) => o.value)).toEqual(["Berlin", "Kraków", "Warsaw"]);
    expect(options.dept.map((o) => o.value)).toEqual(["Design", "Engineering"]);
    expect(options.remote.map((o) => o.label)).toEqual(["Hybrid", "On-site", "Remote"]);
    expect(options.type.map((o) => o.label)).toEqual(["Contract", "Full-time", "Internship"]);
    // python is on two of four jobs; tags on every job filter nothing
    expect(options.tag[0].value).toBe("python");
    expect(options.search).toBe(false);
  });

  it("stays quiet for a small uniform page", () => {
    const options = careersFilterOptions([designer, intern]);
    expect(options.location).toEqual([]);
    expect(options.dept).toEqual([]); // one named department plus none
    expect(options.remote).toEqual([]);
    expect(careersFilterOptions([backend]).tag).toEqual([]);
  });

  it("adds search once the list is long", () => {
    const many = Array.from({ length: 6 }, (_, i) => makeJob({ slug: `j${i}` }));
    expect(careersFilterOptions(many).search).toBe(true);
  });
});

describe("groupByDepartment", () => {
  it("groups in job order with the unassigned jobs last", () => {
    const groups = groupByDepartment([intern, backend, designer, sre]);
    expect(groups?.map((g) => [g.department, g.jobs.map((j) => j.slug)])).toEqual([
      ["Engineering", ["backend", "sre"]],
      ["Design", ["designer"]],
      ["", ["intern"]],
    ]);
  });

  it("is a flat list below two departments", () => {
    expect(groupByDepartment([backend, sre, intern])).toBeNull();
    expect(groupByDepartment([])).toBeNull();
  });
});
