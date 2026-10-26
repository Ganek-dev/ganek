import { describe, expect, it } from "vitest";

import {
  CUSTOM_NAME_HINT,
  EMBED_DOCS_URL,
  SHARE_PRESETS,
  customShareName,
  shareUrl,
  sourceLabelFor,
} from "./share-links";

describe("shareUrl", () => {
  it("appends src to a clean job URL", () => {
    expect(shareUrl("https://jobs.acme.com/jobs/dev", "linkedin")).toBe(
      "https://jobs.acme.com/jobs/dev?src=linkedin",
    );
  });

  it("joins with & when the URL already has a query", () => {
    expect(shareUrl("https://x.test/c/acme/jobs/dev?preview=t", "newsletter")).toBe(
      "https://x.test/c/acme/jobs/dev?preview=t&src=newsletter",
    );
  });
});

describe("customShareName", () => {
  it.each([
    ["LinkedIn Q4 push", null],
    [" Newsletter-Q4 ", "newsletter-q4"],
    ["q4_push", "q4_push"],
    ["a".repeat(41), null],
    ["", null],
    ["linkedin", "linkedin"],
  ])("%j -> %j", (raw, expected) => {
    expect(customShareName(raw)).toBe(expected);
  });
});

describe("sourceLabelFor", () => {
  it("names known buckets as themselves and everything else as a link", () => {
    expect(sourceLabelFor("linkedin")).toBe("linkedin");
    expect(sourceLabelFor("x")).toBe("x");
    expect(sourceLabelFor("newsletter")).toBe("link:newsletter");
    expect(sourceLabelFor("q4_push")).toBe("link:q4_push");
  });

  it("agrees with the page's resolver for alias names", () => {
    // Google for Jobs' utm value is an alias of the google bucket (lib/source.ts)
    expect(sourceLabelFor("google_jobs")).toBe("google");
    expect(sourceLabelFor("google_jobs_apply")).toBe("google");
  });
});

describe("constants", () => {
  it("offers the four presets in the spec's order", () => {
    expect(SHARE_PRESETS.map((p) => p.name)).toEqual(["linkedin", "indeed", "x", "newsletter"]);
    expect(SHARE_PRESETS.map((p) => p.label)).toEqual(["LinkedIn", "Indeed", "X", "Newsletter"]);
  });

  it("points at the embed docs and explains the name rule without dashes", () => {
    expect(EMBED_DOCS_URL).toBe("https://ganek.dev/api-embed/");
    expect(CUSTOM_NAME_HINT).toBe("letters, digits, - or _ only, up to 40");
    expect(CUSTOM_NAME_HINT).not.toMatch(/[–—]/);
  });
});
