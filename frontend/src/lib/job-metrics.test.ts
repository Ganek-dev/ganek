import { describe, expect, it } from "vitest";

import {
  APPLY_RATE_MIN_VIEWS,
  REF_ROW_MIN_VIEWS,
  VIEWS_TOOLTIP,
  applyRate,
  formatCount,
  sourceRows,
} from "./job-metrics";

describe("applyRate", () => {
  it("is hidden under the view threshold (spec 6)", () => {
    expect(APPLY_RATE_MIN_VIEWS).toBe(20);
    expect(applyRate(19, 5)).toBeNull();
    expect(applyRate(3, 1)).toBeNull();
    expect(applyRate(0, 0)).toBeNull();
  });

  it("is applications over views, rounded, from the threshold on", () => {
    expect(applyRate(20, 5)).toBe("25%");
    expect(applyRate(100, 10)).toBe("10%");
    expect(applyRate(1204, 7)).toBe("1%");
    expect(applyRate(30, 0)).toBe("0%");
  });
});

describe("sourceRows", () => {
  const views = { linkedin: 40, "ref:a.example": 2, "ref:b.example": 7, other: 1 };
  const applications = { linkedin: 4, "ref:a.example": 1, direct: 1 };

  it("unions both maps, sorted by views then applications then name", () => {
    expect(sourceRows(views, applications).map((row) => row.source)).toEqual([
      "linkedin",
      "ref:b.example",
      "ref:a.example",
      "other",
      "direct",
    ]);
  });

  it("keeps a thin ref: row when it produced an application", () => {
    const row = sourceRows(views, applications).find((r) => r.source === "ref:a.example");
    expect(row).toEqual({ source: "ref:a.example", views: 2, applications: 1, applyRate: null });
  });

  it("drops ref: rows under the threshold with no application", () => {
    expect(REF_ROW_MIN_VIEWS).toBe(5);
    expect(sourceRows({ "ref:c.example": 3 }, {})).toEqual([]);
    expect(sourceRows({ "ref:c.example": 5 }, {}).map((r) => r.source)).toEqual(["ref:c.example"]);
  });

  it("never hides a named bucket, however thin", () => {
    expect(sourceRows({ xing: 1 }, {}).map((r) => r.source)).toEqual(["xing"]);
  });

  it("carries the row apply rate under the same threshold", () => {
    const [row] = sourceRows({ linkedin: 40 }, { linkedin: 4 });
    expect(row.applyRate).toBe("10%");
  });
});

describe("copy", () => {
  it("formats counts with thousands separators", () => {
    expect(formatCount(1204)).toBe("1,204");
    expect(formatCount(0)).toBe("0");
  });

  it("says views, never visitors", () => {
    expect(VIEWS_TOOLTIP).toMatch(/Page loads by people/);
    expect(VIEWS_TOOLTIP).not.toMatch(/visitor/i);
    expect(VIEWS_TOOLTIP).not.toMatch(/[–—]/);
  });
});
