import { describe, expect, it } from "vitest";

import { locationPolicyHint } from "./location-policy";

describe("locationPolicyHint", () => {
  it.each([
    ["Berlin or remote (EU)", "onsite", "remote"],
    ["Munich, home office possible", "onsite", "remote"],
    ["Anywhere in the EU", "onsite", "remote"],
    ["Work from home, Germany", "onsite", "remote"],
    ["Berlin (hybrid)", "onsite", "hybrid"],
    ["Berlin, on-site", "remote", "on-site"],
    ["Onsite in Hamburg", "remote", "on-site"],
    ["Hamburg, in-office", "remote", "on-site"],
    ["Hybrid, Vienna", "remote", "hybrid"],
  ] as const)("warns for %s with policy %s", (location, policy, word) => {
    expect(locationPolicyHint(location, policy)).toContain(`mentions ${word} work`);
  });

  it.each([
    ["Berlin", "onsite"],
    ["Berlin (no remote)", "onsite"],
    ["Berlin, non-remote", "onsite"],
    ["Anywhere in the EU", "remote"],
    ["Berlin or remote (EU)", "remote"],
    ["Berlin, remote weeks are fine", "hybrid"],
    ["Berlin, on-site two days", "hybrid"],
    ["", "onsite"],
    ["Remoteville", "onsite"],
  ] as const)("stays quiet for %s with policy %s", (location, policy) => {
    expect(locationPolicyHint(location, policy)).toBeNull();
  });

  it("names the selected policy", () => {
    expect(locationPolicyHint("Berlin or remote (EU)", "onsite")).toContain(
      "remote policy is On-site",
    );
  });
});
