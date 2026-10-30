import { describe, expect, it } from "vitest";

import { placeholderHelp } from "./email-placeholders";

describe("placeholderHelp", () => {
  it("lists the computed phrase's possible values", () => {
    expect(placeholderHelp("expires_phrase").example).toContain("in 3 days");
    expect(placeholderHelp("days_left_phrase").example).toContain("1 day left");
    expect(placeholderHelp("candidate_first_name").label).toBe("Candidate first name");
  });

  it("falls back to the name itself", () => {
    expect(placeholderHelp("made_up")).toEqual({ label: "made_up", example: "" });
  });
});
