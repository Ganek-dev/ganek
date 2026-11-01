import { describe, expect, it } from "vitest";

import { formatSendAfter, PRESET_LABELS, presetSendAfter } from "./send-after";

describe("presetSendAfter", () => {
  it("tomorrow morning is 09:00 local on the next calendar day", () => {
    const now = new Date(2026, 10, 6, 22, 30); // Fri 6 Nov 2026 22:30 local
    expect(presetSendAfter("tomorrow", now)).toMatch(/^2026-11-07T09:00:00[+-]\d{2}:\d{2}$/);
    expect(presetSendAfter("in_3_days", now)).toMatch(/^2026-11-09T09:00:00/);
    expect(presetSendAfter("now", now)).toBeNull();
  });

  it("carries the local offset so the instant is 09:00 local in any zone", () => {
    const now = new Date(2026, 10, 6, 22, 30);
    const iso = presetSendAfter("tomorrow", now) as string;
    expect(new Date(iso).getTime()).toBe(new Date(2026, 10, 7, 9, 0, 0).getTime());
    const later = presetSendAfter("in_3_days", new Date(2026, 11, 30, 8, 0)) as string;
    expect(later).toMatch(/^2027-01-02T09:00:00/);
    expect(new Date(later).getTime()).toBe(new Date(2027, 0, 2, 9, 0, 0).getTime());
  });

  it("labels every preset", () => {
    expect(PRESET_LABELS).toEqual({
      now: "Send now",
      tomorrow: "Tomorrow morning",
      in_3_days: "In 3 days",
    });
  });
});

describe("formatSendAfter", () => {
  const now = new Date(2026, 10, 6, 22, 30); // Fri 6 Nov 2026

  it("shows weekday and time within the next 6 days", () => {
    expect(formatSendAfter(new Date(2026, 10, 7, 9, 0).toISOString(), now)).toBe("Sat 09:00");
    expect(formatSendAfter(new Date(2026, 10, 12, 9, 0).toISOString(), now)).toBe("Thu 09:00");
  });

  it("adds the date from 7 days on", () => {
    expect(formatSendAfter(new Date(2026, 10, 13, 9, 0).toISOString(), now)).toBe(
      "Fri 13 Nov 09:00",
    );
  });
});
