import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import robots from "./robots";
import sitemap from "./sitemap";

const { fetchInstanceMode, singleCompanyPage } = vi.hoisted(() => ({
  fetchInstanceMode: vi.fn(),
  singleCompanyPage: vi.fn(),
}));

vi.mock("@/lib/public-api", () => ({
  fetchInstanceMode,
  publicApi: { singleCompanyPage },
}));

beforeEach(() => {
  process.env.GANEK_PUBLIC_BASE_URL = "https://jobs.example.com";
});

afterEach(() => {
  delete process.env.GANEK_PUBLIC_BASE_URL;
  vi.clearAllMocks();
});

describe("sitemap", () => {
  it("lists the root, privacy page and every published job in single mode", async () => {
    fetchInstanceMode.mockResolvedValue("single");
    singleCompanyPage.mockResolvedValue({
      company: { name: "Acme" },
      jobs: [
        { slug: "python-dev", published_at: "2026-07-21T12:00:00Z" },
        { slug: "designer", published_at: null },
      ],
    });

    const entries = await sitemap();
    expect(entries.map((e) => e.url)).toEqual([
      "https://jobs.example.com/",
      "https://jobs.example.com/privacy",
      "https://jobs.example.com/jobs/python-dev",
      "https://jobs.example.com/jobs/designer",
    ]);
    expect(entries[2].lastModified).toBe("2026-07-21T12:00:00Z");
  });

  it("is empty in multi mode — tenant slugs are not enumerable", async () => {
    fetchInstanceMode.mockResolvedValue("multi");
    expect(await sitemap()).toEqual([]);
    expect(singleCompanyPage).not.toHaveBeenCalled();
  });

  it("is empty before setup completes", async () => {
    fetchInstanceMode.mockResolvedValue("single");
    singleCompanyPage.mockResolvedValue(null);
    expect(await sitemap()).toEqual([]);
  });
});

describe("robots", () => {
  it("blocks admin and tokened candidate surfaces, links the sitemap", () => {
    const out = robots();
    const rule = Array.isArray(out.rules) ? out.rules[0] : out.rules;
    expect(rule?.disallow).toEqual(
      expect.arrayContaining(["/admin", "/quiz/", "/application/", "/interview/"]),
    );
    expect(out.sitemap).toBe("https://jobs.example.com/sitemap.xml");
  });
});
