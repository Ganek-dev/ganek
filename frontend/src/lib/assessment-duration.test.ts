import { describe, expect, it } from "vitest";

import { assessmentDuration, assessmentMinutes } from "./assessment-duration";

describe("assessmentDuration", () => {
  it("is questions x seconds rounded up to whole minutes", () => {
    expect(assessmentMinutes(8, 20)).toBe(3);
    expect(assessmentDuration(8, 20)).toBe("about 3 minutes");
    expect(assessmentDuration(12, 25)).toBe("about 5 minutes");
  });

  it("never says zero and keeps one minute singular", () => {
    expect(assessmentMinutes(2, 20)).toBe(1);
    expect(assessmentDuration(2, 20)).toBe("about 1 minute");
  });

  it("promises no number without a fixed per-question limit", () => {
    expect(assessmentMinutes(8, null)).toBeNull();
    expect(assessmentDuration(8, null)).toBe("a few minutes");
    expect(assessmentDuration(undefined, undefined)).toBe("a few minutes");
  });
});
