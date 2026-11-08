import { afterEach, describe, expect, it, vi } from "vitest";

import { GET as robotsGet } from "./robots/route";
import { GET as sitemapGet } from "./sitemap/route";

const { companyPage, fetchInstanceInfo } = vi.hoisted(() => ({
  companyPage: vi.fn(),
  fetchInstanceInfo: vi.fn(),
}));

vi.mock("@/lib/public-api", () => ({ fetchInstanceInfo, publicApi: { companyPage } }));

const params = (slug: string) => ({ params: Promise.resolve({ slug }) });
const request = new Request("https://careers.acme.com/sitemap.xml");

afterEach(() => {
  vi.clearAllMocks();
});

describe("tenant sitemap route", () => {
  it("renders the tenant's jobs on its careers URL", async () => {
    companyPage.mockResolvedValue({
      company: { slug: "acme", careers_url: "https://careers.acme.com" },
      jobs: [{ slug: "dev", published_at: null }],
    });
    const res = await sitemapGet(request, params("acme"));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("application/xml");
    const body = await res.text();
    expect(body).toContain("<loc>https://careers.acme.com/jobs/dev</loc>");
    expect(companyPage).toHaveBeenCalledWith("acme");
  });

  it("404s an unknown tenant, a backend without careers_url and a backend error", async () => {
    companyPage.mockResolvedValueOnce(null);
    expect((await sitemapGet(request, params("nope"))).status).toBe(404);
    companyPage.mockResolvedValueOnce({ company: { slug: "acme" }, jobs: [] });
    expect((await sitemapGet(request, params("acme"))).status).toBe(404);
    companyPage.mockRejectedValueOnce(new Error("Backend responded 503"));
    expect((await sitemapGet(request, params("acme"))).status).toBe(404);
  });
});

describe("tenant robots route", () => {
  it("points crawlers at the host's own sitemap", async () => {
    companyPage.mockResolvedValue({
      company: { slug: "acme", careers_url: "https://acme.ganek.io" },
      jobs: [],
    });
    fetchInstanceInfo.mockResolvedValue({ mode: "multi", demo: false });
    const res = await robotsGet(request, params("acme"));
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Sitemap: https://acme.ganek.io/sitemap.xml");
  });

  it("disallows everything on a demo instance and 404s an unknown tenant", async () => {
    companyPage.mockResolvedValueOnce({
      company: { slug: "acme", careers_url: "https://acme.ganek.io" },
      jobs: [],
    });
    fetchInstanceInfo.mockResolvedValue({ mode: "multi", demo: true });
    expect(await (await robotsGet(request, params("acme"))).text()).toBe(
      "User-Agent: *\nDisallow: /\n",
    );
    companyPage.mockResolvedValueOnce(null);
    expect((await robotsGet(request, params("nope"))).status).toBe(404);
  });
});
