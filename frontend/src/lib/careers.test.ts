import { describe, expect, it } from "vitest";

import { canonicalCareersUrl, canonicalMetadata, careersDisplay, careersUrl } from "./careers";

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

describe("careersUrl", () => {
  it("serves multi mode under /c/{slug} and single mode at the root", () => {
    expect(careersUrl("multi", "acme")).toBe(`${window.location.origin}/c/acme`);
    expect(careersUrl("single", "acme")).toBe(window.location.origin);
  });

  it("uses the verified custom domain when the server sends one", () => {
    expect(careersUrl("multi", "acme", "careers.acme.com")).toBe("https://careers.acme.com");
    expect(careersDisplay("multi", "acme", "careers.acme.com")).toBe("careers.acme.com");
  });

  it("falls back to the slug URL without a domain", () => {
    expect(careersUrl("multi", "acme", null)).toBe(`${window.location.origin}/c/acme`);
    expect(careersDisplay("multi", "acme", "")).toBe(`${window.location.host}/c/acme`);
  });
});
