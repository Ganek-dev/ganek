import { describe, expect, it } from "vitest";

import { trialDaysLeft, trialDaysText } from "./trial";

const NOW = Date.parse("2026-11-08T09:00:00Z");

describe("trialDaysLeft", () => {
  it("counts a fresh trial as 14 days", () => {
    expect(trialDaysLeft("2026-11-22T09:00:00Z", NOW)).toBe(14);
  });

  it("rounds a part day up", () => {
    expect(trialDaysLeft("2026-11-08T15:00:00Z", NOW)).toBe(1);
    expect(trialDaysLeft("2026-11-10T08:00:00Z", NOW)).toBe(2);
  });

  it("is 0 once the trial is over or the date is unreadable", () => {
    expect(trialDaysLeft("2026-11-08T09:00:00Z", NOW)).toBe(0);
    expect(trialDaysLeft("2026-11-01T09:00:00Z", NOW)).toBe(0);
    expect(trialDaysLeft("not a date", NOW)).toBe(0);
  });

  it("says day or days", () => {
    expect(trialDaysText(1)).toBe("1 day left");
    expect(trialDaysText(9)).toBe("9 days left");
  });
});
