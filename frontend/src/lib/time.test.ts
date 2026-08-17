import { describe, expect, it } from "vitest";

import { relativeTime } from "./time";

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
