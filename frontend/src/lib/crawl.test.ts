import { describe, expect, it } from "vitest";

import { ROBOTS_DISALLOW, tenantRobotsTxt, tenantSitemapXml } from "./crawl";

describe("tenantSitemapXml", () => {
  it("lists landing, privacy and every job on the canonical careers URL", () => {
    const xml = tenantSitemapXml("https://careers.acme.com", [
      { slug: "python-dev", published_at: "2026-07-21T12:00:00Z" },
      { slug: "designer", published_at: null },
    ]);
    const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
    expect(locs).toEqual([
      "https://careers.acme.com/",
      "https://careers.acme.com/privacy",
      "https://careers.acme.com/jobs/python-dev",
      "https://careers.acme.com/jobs/designer",
    ]);
    expect(xml).toContain("<lastmod>2026-07-21T12:00:00Z</lastmod>");
    expect(xml.match(/<lastmod>/g)).toHaveLength(1);
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
  });

  it("works on a slug careers URL and escapes XML", () => {
    const xml = tenantSitemapXml("https://app.ganek.io/c/acme/", [
      { slug: "r&d", published_at: null },
    ]);
    expect(xml).toContain("<loc>https://app.ganek.io/c/acme/</loc>");
    expect(xml).toContain("<loc>https://app.ganek.io/c/acme/jobs/r%26d</loc>");
    expect(xml).not.toContain("r&d");
  });
});

describe("tenantRobotsTxt", () => {
  it("disallows the capability surfaces and links the host's sitemap", () => {
    const txt = tenantRobotsTxt("https://careers.acme.com", false);
    for (const path of ROBOTS_DISALLOW) expect(txt).toContain(`Disallow: ${path}\n`);
    expect(txt).toContain("Sitemap: https://careers.acme.com/sitemap.xml");
  });

  it("disallows everything on a demo instance", () => {
    expect(tenantRobotsTxt("https://careers.acme.com", true)).toBe(
      "User-Agent: *\nDisallow: /\n",
    );
  });
});
