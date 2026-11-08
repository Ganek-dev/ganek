import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { planLimitMessage, planLimitOf } from "./plan-limit";

const body = {
  code: "plan_limit",
  limit: 1,
  upgrade_url: "https://billing.example/upgrade",
  message: "Your plan allows 1 live job.",
};

describe("planLimitOf", () => {
  it("reads the limit and upgrade link off a 402 plan_limit", () => {
    expect(planLimitOf(new ApiError(402, body.message, body))).toEqual({
      limit: 1,
      upgradeUrl: "https://billing.example/upgrade",
    });
  });

  it("keeps a 402 without an upgrade link", () => {
    expect(planLimitOf(new ApiError(402, "x", { ...body, upgrade_url: null }))).toEqual({
      limit: 1,
      upgradeUrl: null,
    });
  });

  it("ignores every other error, the A4 quota 409 included", () => {
    expect(planLimitOf(new ApiError(409, "Active job limit reached (50)."))).toBeNull();
    expect(planLimitOf(new ApiError(402, "Payment Required"))).toBeNull();
    expect(planLimitOf(new Error("network"))).toBeNull();
  });
});

describe("planLimitMessage", () => {
  it("offers an admin the upgrade", () => {
    expect(planLimitMessage({ limit: 1, upgradeUrl: null }, true)).toBe(
      "Your plan allows 1 live job. Close a job or upgrade the plan to publish another.",
    );
  });

  it("sends a recruiter to their admin", () => {
    expect(planLimitMessage({ limit: 5, upgradeUrl: null }, false)).toBe(
      "Your plan allows 5 live jobs. Close a job or ask your admin to upgrade the plan.",
    );
  });
});
