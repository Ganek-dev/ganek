import { describe, expect, it } from "vitest";

import { relativeAge, relativeTime, shortTime } from "./time";

describe("relativeTime", () => {
  const now = new Date("2026-08-17T12:00:00Z");

  it("buckets ages like the cards it replaced", () => {
    expect(relativeTime("2026-08-17T11:59:30Z", now)).toBe("just now");
    expect(relativeTime("2026-08-17T11:55:00Z", now)).toBe("5m ago");
    expect(relativeTime("2026-08-17T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-08-15T12:00:00Z", now)).toBe("2d ago");
    expect(relativeTime("2026-07-27T12:00:00Z", now)).toBe("3w ago");
  });

  it("never goes negative on clock skew", () => {
    expect(relativeTime("2026-08-17T12:00:05Z", now)).toBe("just now");
  });
});

describe("formatDay", () => {
  it("formats day, short month and year", async () => {
    const { formatDay } = await import("./time");
    expect(formatDay(new Date(2026, 9, 31, 12, 0).toISOString())).toBe("31 Oct 2026");
  });
});

describe("shortTime", () => {
  it("formats a time of day and is empty for anything unusable", () => {
    expect(shortTime("2026-11-08T17:13:00Z")).toMatch(/^\d{2}:\d{2}$/);
    expect(shortTime("not a date")).toBe("");
    expect(shortTime(undefined)).toBe("");
  });
});

describe("relativeAge", () => {
  const now = new Date("2026-10-24T12:00:00Z");
  it.each([
    ["2026-10-24T11:59:30Z", { unit: "now", n: 0 }],
    ["2026-10-24T11:55:00Z", { unit: "m", n: 5 }],
    ["2026-10-24T09:00:00Z", { unit: "h", n: 3 }],
    ["2026-10-21T12:00:00Z", { unit: "d", n: 3 }],
    ["2026-10-03T12:00:00Z", { unit: "w", n: 3 }],
  ])("%s", (iso, expected) => {
    expect(relativeAge(iso, now)).toEqual(expected);
  });
});
