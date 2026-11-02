import { describe, expect, it } from "vitest";

import {
  clearNarrowing,
  countActive,
  DEFAULT_FILTERS,
  filtersToParams,
  parseFilters,
  toApiFilters,
  type ApplicantFilters,
} from "./applicant-filters";

const FULL: ApplicantFilters = {
  job: "job-1",
  stage: "screening",
  q: "erika",
  sort: "score_desc",
  score: 60,
  quiz: "completed",
  source: "linkedin",
  flagged: true,
  days: 30,
  screening: "match",
  waiting: "team",
};

describe("parseFilters", () => {
  it("returns the defaults for an empty query", () => {
    expect(parseFilters(new URLSearchParams())).toEqual(DEFAULT_FILTERS);
  });

  it("round-trips every parameter", () => {
    const params = filtersToParams(FULL);
    expect(parseFilters(params)).toEqual(FULL);
  });

  it("falls back to the default on a value it does not know", () => {
    const params = new URLSearchParams(
      "score=abc&days=0&sort=sideways&quiz=maybe&stage=limbo&flagged=perhaps",
    );
    expect(parseFilters(params)).toEqual(DEFAULT_FILTERS);
  });

  it("clamps score to 0..100 and days to 1..365", () => {
    expect(parseFilters(new URLSearchParams("score=101")).score).toBeNull();
    expect(parseFilters(new URLSearchParams("score=0")).score).toBe(0);
    expect(parseFilters(new URLSearchParams("days=366")).days).toBeNull();
    expect(parseFilters(new URLSearchParams("days=7")).days).toBe(7);
  });

  it("accepts the stage-age sort keys", () => {
    expect(parseFilters(new URLSearchParams("sort=stage_age_desc")).sort).toBe("stage_age_desc");
    expect(parseFilters(new URLSearchParams("sort=stage_age_asc")).sort).toBe("stage_age_asc");
  });

  it("reads flagged=false as the clean filter", () => {
    expect(parseFilters(new URLSearchParams("flagged=false")).flagged).toBe(false);
  });
});

describe("filtersToParams", () => {
  it("is empty for the defaults so the plain link stays clean", () => {
    expect(filtersToParams(DEFAULT_FILTERS).toString()).toBe("");
  });

  it("omits defaults and keeps extra params such as the selected applicant", () => {
    const params = filtersToParams({ ...DEFAULT_FILTERS, q: "ben" }, { selected: "app-9" });
    expect(params.get("q")).toBe("ben");
    expect(params.get("selected")).toBe("app-9");
    expect(params.has("sort")).toBe(false);
    expect(params.has("stage")).toBe(false);
  });

  it("writes flagged=false explicitly", () => {
    expect(filtersToParams({ ...DEFAULT_FILTERS, flagged: false }).get("flagged")).toBe("false");
  });
});

describe("toApiFilters", () => {
  it("maps the URL names to the API names and drops defaults", () => {
    expect(toApiFilters(FULL)).toEqual({
      job_id: "job-1",
      stage: "screening",
      q: "erika",
      sort: "score_desc",
      score_min: 60,
      quiz: "completed",
      source: "linkedin",
      flagged: true,
      since_days: 30,
      screening: "match",
      waiting: "team",
    });
    expect(toApiFilters(DEFAULT_FILTERS)).toEqual({});
  });

  it("drops a blank search", () => {
    expect(toApiFilters({ ...DEFAULT_FILTERS, q: "   " })).toEqual({});
  });
});

describe("countActive", () => {
  it("counts the narrowing filters, not job, stage or sort", () => {
    expect(countActive(DEFAULT_FILTERS)).toBe(0);
    expect(countActive({ ...DEFAULT_FILTERS, job: "j", stage: "new", sort: "name_asc" })).toBe(0);
    expect(countActive(FULL)).toBe(8);
    expect(countActive({ ...DEFAULT_FILTERS, flagged: false })).toBe(1);
  });
});

describe("screening filter", () => {
  it("round-trips screening and maps it to the API param", () => {
    const parsed = parseFilters(new URLSearchParams("screening=mismatch"));
    expect(parsed.screening).toBe("mismatch");
    expect(filtersToParams(parsed).get("screening")).toBe("mismatch");
    expect(toApiFilters(parsed).screening).toBe("mismatch");
    expect(countActive(parsed)).toBe(1);
  });

  it("drops an unknown screening value and omits the default", () => {
    expect(parseFilters(new URLSearchParams("screening=sideways")).screening).toBeNull();
    expect(filtersToParams(DEFAULT_FILTERS).has("screening")).toBe(false);
    expect(toApiFilters(DEFAULT_FILTERS).screening).toBeUndefined();
  });
});

describe("waiting filter", () => {
  it("round-trips waiting and maps it to the API param", () => {
    const parsed = parseFilters(new URLSearchParams("waiting=candidate"));
    expect(parsed.waiting).toBe("candidate");
    expect(filtersToParams(parsed).get("waiting")).toBe("candidate");
    expect(toApiFilters(parsed).waiting).toBe("candidate");
  });

  it("counts as an active filter and clearNarrowing resets it", () => {
    const waiting = { ...DEFAULT_FILTERS, waiting: "team" as const };
    expect(countActive(waiting)).toBe(1);
    expect(clearNarrowing(FULL).waiting).toBeNull();
    expect(countActive(clearNarrowing(FULL))).toBe(0);
  });

  it("drops an unknown waiting value and omits the default", () => {
    expect(parseFilters(new URLSearchParams("waiting=nobody")).waiting).toBeNull();
    expect(filtersToParams(DEFAULT_FILTERS).has("waiting")).toBe(false);
    expect(toApiFilters(DEFAULT_FILTERS).waiting).toBeUndefined();
  });
});
