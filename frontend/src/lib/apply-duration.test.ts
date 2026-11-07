import { describe, expect, it } from "vitest";

import { applyEffort, applyFieldCount, applyMinutes } from "./apply-duration";

describe("apply duration", () => {
  it("counts name, email and the CV on a plain form", () => {
    expect(applyFieldCount({})).toBe(3);
    expect(applyMinutes({})).toBe(2);
    expect(applyEffort({})).toBe("three fields, about two minutes");
  });

  it("drops the CV upload on the demo", () => {
    expect(applyFieldCount({ demo: true })).toBe(2);
    expect(applyEffort({ demo: true })).toBe("two fields, about one minute");
  });

  it("adds required screening questions and acknowledgments, not optional ones", () => {
    const shape = {
      screeningQuestions: [
        { type: "yes_no" as const, required: true },
        { type: "acknowledgment" as const, required: false },
        { type: "short_text" as const, required: false },
      ],
    };
    expect(applyFieldCount(shape)).toBe(5);
    expect(applyEffort(shape)).toBe("five fields, about three minutes");
  });

  it("falls back to digits past ten", () => {
    const screeningQuestions = Array.from({ length: 10 }, () => ({
      type: "yes_no" as const,
      required: true,
    }));
    expect(applyEffort({ screeningQuestions })).toBe("13 fields, about seven minutes");
  });
});
