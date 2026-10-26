import { describe, expect, it } from "vitest";

import {
  bucketFromReferrer,
  normalizeLinkName,
  registrableDomain,
  resolveSource,
} from "./source";

describe("registrableDomain", () => {
  it.each([
    ["www.google.com", "google.com"],
    ["blog.example.co.uk", "example.co.uk"],
    ["careers.acme.com", "acme.com"],
    ["example.com", "example.com"],
    ["a.b.c.example.org", "example.org"],
    ["localhost", "localhost"],
  ])("%s -> %s", (host, expected) => {
    expect(registrableDomain(host)).toBe(expected);
  });
});

describe("bucketFromReferrer", () => {
  it.each([
    ["https://www.google.com/", null, "google"],
    ["https://www.google.de/search?q=ganek", null, "google"],
    ["https://www.google.co.uk/", null, "google"],
    ["https://www.linkedin.com/feed/", null, "linkedin"],
    ["https://lnkd.in/abc", null, "linkedin"],
    ["https://de.indeed.com/jobs?q=x", null, "indeed"],
    ["https://www.facebook.com/", null, "facebook"],
    ["https://fb.me/x", null, "facebook"],
    ["https://t.co/xyz", null, "x"],
    ["https://x.com/someone", null, "x"],
    ["https://twitter.com/someone", null, "x"],
    ["https://www.glassdoor.de/Job/x", null, "glassdoor"],
    ["https://www.xing.com/jobs", null, "xing"],
    ["https://www.stepstone.de/x", null, "stepstone"],
    ["https://news.ycombinator.com/item?id=1", null, "hn"],
    ["https://old.reddit.com/r/x", null, "reddit"],
    ["https://redd.it/abc", null, "reddit"],
    ["https://github.com/Ganek-dev/ganek", null, "github"],
    ["https://careers.acme.com/", "www.acme.com", "website"],
    ["https://www.acme.com/about", "www.acme.com", "website"],
    ["https://blog.example.co.uk/post?x=1#y", null, "ref:example.co.uk"],
    ["https://example.com/", null, "ref:example.com"],
    ["https://EXAMPLE.com/", null, "ref:example.com"],
    ["not a url", null, "direct"],
    ["", null, "direct"],
    [null, null, "direct"],
    ["http://localhost:3000/c/acme", null, "direct"],
    ["https://127.0.0.1/", null, "direct"],
  ])("%s (website %s) -> %s", (referer, website, expected) => {
    expect(bucketFromReferrer(referer, website)).toBe(expected);
  });
});

describe("normalizeLinkName", () => {
  it.each([
    ["newsletter", "newsletter"],
    [" Q4_Push-2 ", "q4_push-2"],
    ["", null],
    ["has space", null],
    ["a".repeat(41), null],
    ["ünïcode", null],
    ["<script>", null],
  ])("%s -> %s", (raw, expected) => {
    expect(normalizeLinkName(raw)).toBe(expected);
  });
});

describe("resolveSource", () => {
  const linkedin = "https://www.linkedin.com/jobs/";
  it("prefers src, then utm_source, then the referrer, then direct", () => {
    expect(resolveSource({ src: "newsletter", referer: linkedin, websiteHost: null })).toBe(
      "link:newsletter",
    );
    expect(
      resolveSource({ utm_source: "jobboard", referer: linkedin, websiteHost: null }),
    ).toBe("link:jobboard");
    expect(resolveSource({ referer: linkedin, websiteHost: null })).toBe("linkedin");
    expect(resolveSource({ referer: null, websiteHost: null })).toBe("direct");
  });

  it("maps a src equal to a known bucket onto the bucket itself", () => {
    expect(resolveSource({ src: "linkedin", referer: null, websiteHost: null })).toBe("linkedin");
    expect(resolveSource({ src: "LinkedIn", referer: null, websiteHost: null })).toBe("linkedin");
    expect(resolveSource({ src: "ref:example.com", referer: null, websiteHost: null })).toBe(
      "ref:example.com",
    );
  });

  it("falls through to the next rule when a value is invalid", () => {
    expect(
      resolveSource({ src: "<bad value>", utm_source: "jobboard", referer: linkedin, websiteHost: null }),
    ).toBe("link:jobboard");
    expect(
      resolveSource({ src: "<bad>", utm_source: "also bad", referer: linkedin, websiteHost: null }),
    ).toBe("linkedin");
  });

  it("takes the first value of a repeated query parameter", () => {
    expect(
      resolveSource({ src: ["newsletter", "other"], referer: null, websiteHost: null }),
    ).toBe("link:newsletter");
  });
});
