import { describe, expect, it } from "vitest";

import { canonicalCareersUrl, canonicalMetadata } from "./careers";

describe("canonicalCareersUrl", () => {
  it("uses the server's careers URL, the custom domain once verified", () => {
    const company = { careers_url: "https://careers.acme.com" };
    expect(canonicalCareersUrl(company)).toBe("https://careers.acme.com");
    expect(canonicalCareersUrl(company, "backend-engineer")).toBe(
      "https://careers.acme.com/jobs/backend-engineer",
    );
  });

  it("keeps the slug URL when there is no domain", () => {
    const company = { careers_url: "https://app.ganek.io/c/acme/" };
    expect(canonicalCareersUrl(company, "qa")).toBe("https://app.ganek.io/c/acme/jobs/qa");
  });

  it("emits nothing without a careers URL", () => {
    expect(canonicalCareersUrl({})).toBeNull();
    expect(canonicalCareersUrl({ careers_url: null }, "qa")).toBeNull();
    expect(canonicalMetadata({})).toEqual({});
  });

  it("builds the Next alternates block", () => {
    expect(canonicalMetadata({ careers_url: "https://careers.acme.com" }, "qa")).toEqual({
      alternates: { canonical: "https://careers.acme.com/jobs/qa" },
    });
  });
});
