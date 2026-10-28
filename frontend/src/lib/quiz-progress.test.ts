import { describe, expect, it } from "vitest";

import { answeredSummary } from "./quiz-progress";

describe("answeredSummary", () => {
  it("keeps the 'N of N answered' line when nothing timed out", () => {
    expect(answeredSummary({ answered: 8, timed_out: 0, total: 8 })).toBe("8 of 8 answered");
  });

  it("lists timed-out questions instead of counting them as answered", () => {
    expect(answeredSummary({ answered: 6, timed_out: 2, total: 8 })).toBe(
      "6 answered, 2 timed out",
    );
  });

  it("handles an attempt where every question timed out", () => {
    expect(answeredSummary({ answered: 0, timed_out: 3, total: 3 })).toBe(
      "0 answered, 3 timed out",
    );
  });
});
