import { describe, expect, it } from "vitest";

import {
  APPLY_RATE_MIN_VIEWS,
  REF_ROW_MIN_VIEWS,
  APPLICATIONS_TOOLTIP,
  VIEWS_EMPTY_COPY,
  VIEWS_TOOLTIP,
  WINDOW_30D,
  viewsEmptyState,
  applyRate,
  applyRateReason,
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

  it("is n/a when applications outnumber counted views (jobs older than the counter)", () => {
    expect(applyRate(25, 40)).toBeNull();
    expect(applyRateReason(25, 40)).toBe("applications outnumber counted views");
    expect(applyRateReason(19, 5)).toBe("under 20 views");
    expect(applyRateReason(100, 10)).toBeNull();
    expect(applyRate(30, 30)).toBe("100%");
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

  it("carries the row apply rate under the same rules", () => {
    const [row] = sourceRows({ linkedin: 40 }, { linkedin: 4 });
    expect(row.applyRate).toBe("10%");
    const [legacy] = sourceRows({ linkedin: 25 }, { linkedin: 40 });
    expect(legacy.applyRate).toBeNull();
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
    expect(VIEWS_TOOLTIP).not.toMatch(/[\u2013\u2014]/);
    for (const copy of [WINDOW_30D, APPLICATIONS_TOOLTIP]) {
      expect(copy).toMatch(/today and the 29 days before it \(UTC\)/i);
      expect(copy).not.toMatch(/[\u2013\u2014]/);
    }
  });
});

describe("viewsEmptyState", () => {
  it("is null once any view was counted", () => {
    expect(viewsEmptyState("published", 1, 0)).toBeNull();
    expect(viewsEmptyState("closed", 1, 5)).toBeNull();
  });

  it("invites sharing on a live job with nothing counted yet", () => {
    expect(viewsEmptyState("published", 0, 0)).toBe("share");
  });

  it("stays neutral on a closed job: nothing left to share", () => {
    expect(viewsEmptyState("closed", 0, 0)).toBe("closed");
    expect(viewsEmptyState("closed", 0, 5)).toBe("closed");
  });

  it("explains the counter's start when applications predate it", () => {
    expect(viewsEmptyState("published", 0, 5)).toBe("pre-counter");
  });

  it("keeps the three copies free of visitors and dashes", () => {
    expect(VIEWS_EMPTY_COPY.share).toBe("No views yet. Share it:");
    expect(VIEWS_EMPTY_COPY.closed).toBe("No views were counted.");
    expect(VIEWS_EMPTY_COPY["pre-counter"]).toMatch(/counted from the 0\.4\.0 update/);
    for (const copy of Object.values(VIEWS_EMPTY_COPY)) {
      expect(copy).not.toMatch(/visitor/i);
      expect(copy).not.toMatch(/[\u2013\u2014]/);
    }
  });
});
