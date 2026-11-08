import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  canonicalHostRedirectUrl,
  clearDomainCache,
  customDomainRoute,
  isInstanceHost,
  jobLookupPath,
  middleware,
  normalizeHost,
  slugCanonicalPath,
} from "./middleware";

function req(path: string, cookie?: string): NextRequest {
  return new NextRequest(`http://ganek.test${path}`, {
    headers: cookie ? { cookie } : undefined,
  });
}

beforeEach(() => {
  // the requests below are for the instance's own host unless a test says otherwise
  vi.stubEnv("GANEK_PUBLIC_BASE_URL", "http://ganek.test");
  clearDomainCache();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("admin middleware", () => {
  it("redirects cookieless visitors to /login", async () => {
    const res = await middleware(req("/admin/applicants"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://ganek.test/login");
  });

  it("passes requests that carry a session cookie", async () => {
    const res = await middleware(req("/admin/applicants", "ganek_session=whatever"));
    expect(res.headers.get("location")).toBeNull();
  });

  it("guards the cookieless reviewer shell too", async () => {
    const res = await middleware(req("/review/0b9f"));
    expect(res.headers.get("location")).toBe("http://ganek.test/login");
    const ok = await middleware(req("/review/0b9f", "ganek_session=whatever"));
    expect(ok.headers.get("location")).toBeNull();
  });

  it("is scoped to the guarded shells and the careers routes by its matcher", async () => {
    const { config } = await import("./middleware");
    expect(config.matcher).toEqual([
      "/",
      "/privacy",
      "/sitemap.xml",
      "/robots.txt",
      "/login",
      "/setup",
      "/admin/:path*",
      "/review/:path*",
      "/jobs/:jobSlug",
      "/c/:path*",
    ]);
  });

  it("leaves the careers pages and login alone on the instance host", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const path of ["/", "/login", "/privacy"]) {
      const res = await middleware(req(path));
      expect(res.headers.get("location")).toBeNull();
      expect(res.headers.get("x-middleware-rewrite")).toBeNull();
    }
    expect(fetchMock).not.toHaveBeenCalled();
    // slug pages only ask whether the tenant has a verified domain
    const noDomain = vi.fn().mockResolvedValue(new Response("{}", { status: 404 }));
    vi.stubGlobal("fetch", noDomain);
    for (const path of ["/c/acme", "/c/acme/privacy"]) {
      const res = await middleware(req(path));
      expect(res.headers.get("location")).toBeNull();
      expect(res.headers.get("x-middleware-rewrite")).toBeNull();
    }
    expect(noDomain).toHaveBeenCalledTimes(1);
  });
});

describe("public job pages: real 404", () => {
  it("maps both job routes to their backend lookup and nothing else", () => {
    expect(jobLookupPath("/jobs/dev")).toBe("/api/v1/public/company/jobs/dev");
    expect(jobLookupPath("/jobs/dev/")).toBe("/api/v1/public/company/jobs/dev");
    expect(jobLookupPath("/c/acme/jobs/dev")).toBe("/api/v1/public/companies/acme/jobs/dev");
    expect(jobLookupPath("/c/acme")).toBeNull();
    expect(jobLookupPath("/admin/jobs/1")).toBeNull();
    expect(jobLookupPath("/jobs/dev/apply")).toBeNull();
  });

  it("answers 404 for an unknown slug, without a redirect and without view headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    const res = await middleware(req("/c/acme/jobs/nope"));
    expect(res.status).toBe(404);
    expect(res.headers.get("location")).toBeNull();
    // the first call asks for the tenant's custom domain (slug URL 301)
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/public\/companies\/acme\/jobs\/nope$/);
    expect(Object.keys(init.headers as Record<string, string>)).toEqual(["Accept"]);
  });

  it("lets a live job render normally", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    const res = await middleware(req("/jobs/dev"));
    expect(res.status).toBe(200);
    expect(res.headers.get("x-middleware-rewrite")).toBeNull();
  });

  it("does not need a session cookie on a job page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    const res = await middleware(req("/jobs/dev"));
    expect(res.headers.get("location")).toBeNull();
  });

  it("skips the lookup for preview links", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const res = await middleware(req("/jobs/draft?preview=tok"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(res.status).toBe(200);
  });

  it("skips the lookup for client-side navigations and prefetches", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const header of ["rsc", "next-router-prefetch"]) {
      const res = await middleware(
        new NextRequest("http://ganek.test/jobs/nope", { headers: { [header]: "1" } }),
      );
      expect(res.status).toBe(200);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails open when the backend errors or is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));
    expect((await middleware(req("/jobs/dev"))).status).toBe(200);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    expect((await middleware(req("/jobs/dev"))).status).toBe(200);
  });
});

function hostReq(host: string, path: string, headers: Record<string, string> = {}): NextRequest {
  return new NextRequest(`https://${host}${path}`, { headers: { host, ...headers } });
}

function resolveTo(slug: string | null, jobStatus = 200) {
  return vi.fn(async (url: string) => {
    if (url.includes("/public/domains/resolve")) {
      return slug === null
        ? new Response("{}", { status: 404 })
        : Response.json({ slug, domain: "careers.acme.com" });
    }
    return new Response("{}", { status: jobStatus });
  });
}

describe("custom domains: host helpers", () => {
  it("normalizes a Host header like the backend does", () => {
    expect(normalizeHost("Careers.Acme.COM:443")).toBe("careers.acme.com");
    expect(normalizeHost("careers.acme.com.")).toBe("careers.acme.com");
    expect(normalizeHost(null)).toBe("");
  });

  it("never treats the instance host, localhost, IPs or bare names as a custom domain", () => {
    for (const host of ["ganek.test", "localhost", "app.localhost", "10.0.0.4", "[::1]", "frontend", ""]) {
      expect(isInstanceHost(host)).toBe(true);
    }
    expect(isInstanceHost("careers.acme.com")).toBe(false);
  });

  it("maps careers paths to the tenant's routes and nothing else", () => {
    expect(customDomainRoute("/", "acme")).toEqual({ rewrite: "/c/acme" });
    expect(customDomainRoute("/privacy", "acme")).toEqual({ rewrite: "/c/acme/privacy" });
    expect(customDomainRoute("/jobs/dev", "acme")).toEqual({ rewrite: "/c/acme/jobs/dev" });
    expect(customDomainRoute("/jobs/dev/", "acme")).toEqual({ rewrite: "/c/acme/jobs/dev" });
    expect(customDomainRoute("/c/acme/jobs/dev", "acme")).toEqual({ pass: true });
    expect(customDomainRoute("/c/acme", "acme")).toEqual({ pass: true });
    expect(customDomainRoute("/c/globex", "acme")).toEqual({ notFound: true });
    expect(customDomainRoute("/c/globex/jobs/dev", "acme")).toEqual({ notFound: true });
    expect(customDomainRoute("/admin/jobs", "acme")).toEqual({ admin: true });
    expect(customDomainRoute("/login", "acme")).toEqual({ admin: true });
    expect(customDomainRoute("/quiz/tok", "acme")).toEqual({ pass: true });
    expect(customDomainRoute("/sitemap.xml", "acme")).toEqual({
      rewrite: "/c/acme/sitemap",
    });
    expect(customDomainRoute("/robots.txt", "acme")).toEqual({ rewrite: "/c/acme/robots" });
  });
});

describe("custom domains: routing", () => {
  it("serves the tenant's own sitemap and robots.txt on its domain", async () => {
    vi.stubGlobal("fetch", resolveTo("acme"));
    const map = await middleware(hostReq("careers.acme.com", "/sitemap.xml"));
    expect(map.headers.get("x-middleware-rewrite")).toBe(
      "https://careers.acme.com/c/acme/sitemap",
    );
    const robots = await middleware(hostReq("careers.acme.com", "/robots.txt"));
    expect(robots.headers.get("x-middleware-rewrite")).toBe(
      "https://careers.acme.com/c/acme/robots",
    );
  });

  it("leaves the instance sitemap and robots.txt alone on the instance host", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const path of ["/sitemap.xml", "/robots.txt"]) {
      const res = await middleware(req(path));
      expect(res.headers.get("x-middleware-rewrite")).toBeNull();
      expect(res.headers.get("location")).toBeNull();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("serves the tenant's careers page at the domain root, query kept", async () => {
    const fetchMock = resolveTo("acme");
    vi.stubGlobal("fetch", fetchMock);
    const res = await middleware(hostReq("careers.acme.com", "/?src=linkedin"));
    expect(res.headers.get("x-middleware-rewrite")).toBe(
      "https://careers.acme.com/c/acme?src=linkedin",
    );
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toMatch(/\/api\/v1\/public\/domains\/resolve\?host=careers\.acme\.com$/);
  });

  it("rewrites a job page and keeps the real 404 for an unknown job", async () => {
    vi.stubGlobal("fetch", resolveTo("acme"));
    const ok = await middleware(hostReq("careers.acme.com", "/jobs/dev"));
    expect(ok.status).toBe(200);
    expect(ok.headers.get("x-middleware-rewrite")).toBe("https://careers.acme.com/c/acme/jobs/dev");

    clearDomainCache();
    const fetchMock = resolveTo("acme", 404);
    vi.stubGlobal("fetch", fetchMock);
    const gone = await middleware(hostReq("careers.acme.com", "/jobs/nope"));
    expect(gone.status).toBe(404);
    expect(gone.headers.get("x-middleware-rewrite")).toBe(
      "https://careers.acme.com/c/acme/jobs/nope",
    );
    const urls = fetchMock.mock.calls.map(([u]) => u as string);
    expect(urls[1]).toMatch(/\/api\/v1\/public\/companies\/acme\/jobs\/nope$/);
  });

  it("never shows another tenant's pages on a tenant's domain", async () => {
    vi.stubGlobal("fetch", resolveTo("acme"));
    const res = await middleware(hostReq("careers.acme.com", "/c/globex"));
    expect(res.status).toBe(404);
    expect(res.headers.get("x-middleware-rewrite")).toBeNull();
  });

  it("sends signed-in surfaces to the instance host", async () => {
    vi.stubGlobal("fetch", resolveTo("acme"));
    const res = await middleware(hostReq("careers.acme.com", "/admin/jobs?x=1", { cookie: "ganek_session=s" }));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://ganek.test/admin/jobs?x=1");
  });

  it("asks the backend once a minute per host, misses included", async () => {
    const fetchMock = resolveTo(null);
    vi.stubGlobal("fetch", fetchMock);
    await middleware(hostReq("unknown.example.org", "/"));
    await middleware(hostReq("Unknown.Example.org:443", "/"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("serves an unverified or unknown host like the instance host", async () => {
    vi.stubGlobal("fetch", resolveTo(null));
    const res = await middleware(hostReq("unknown.example.org", "/"));
    expect(res.status).toBe(200);
    expect(res.headers.get("x-middleware-rewrite")).toBeNull();
  });

  it("fails open, uncached, when the resolve call errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const res = await middleware(hostReq("careers.acme.com", "/"));
    expect(res.status).toBe(200);
    expect(res.headers.get("x-middleware-rewrite")).toBeNull();
    const fetchMock = resolveTo("acme");
    vi.stubGlobal("fetch", fetchMock);
    const later = await middleware(hostReq("careers.acme.com", "/"));
    expect(later.headers.get("x-middleware-rewrite")).toBe("https://careers.acme.com/c/acme");
  });
});

function domainFor(domain: string | null, jobStatus = 200) {
  return vi.fn(async (url: string) => {
    if (url.includes("/public/domains/by-slug/")) {
      return domain === null
        ? new Response("{}", { status: 404 })
        : Response.json({ slug: "acme", domain });
    }
    if (url.includes("/public/domains/resolve")) return new Response("{}", { status: 404 });
    return new Response("{}", { status: jobStatus });
  });
}

describe("custom domains: slug URL 301", () => {
  it("maps slug URLs to their path on the domain and nothing else", () => {
    expect(slugCanonicalPath("/c/acme")).toEqual({ slug: "acme", path: "/" });
    expect(slugCanonicalPath("/c/acme/")).toEqual({ slug: "acme", path: "/" });
    expect(slugCanonicalPath("/c/acme/privacy")).toEqual({ slug: "acme", path: "/privacy" });
    expect(slugCanonicalPath("/c/acme/jobs/dev")).toEqual({ slug: "acme", path: "/jobs/dev" });
    expect(slugCanonicalPath("/c/acme/jobs")).toBeNull();
    expect(slugCanonicalPath("/c/acme/jobs/dev/apply")).toBeNull();
    expect(slugCanonicalPath("/jobs/dev")).toBeNull();
    expect(slugCanonicalPath("/")).toBeNull();
  });

  it("301s the careers page, a job and the privacy notice to the verified domain, query kept", async () => {
    const fetchMock = domainFor("careers.acme.com");
    vi.stubGlobal("fetch", fetchMock);
    const cases: [string, string][] = [
      ["/c/acme?src=linkedin", "https://careers.acme.com/?src=linkedin"],
      ["/c/acme/jobs/dev", "https://careers.acme.com/jobs/dev"],
      ["/c/acme/privacy/", "https://careers.acme.com/privacy"],
    ];
    for (const [path, location] of cases) {
      const res = await middleware(req(path));
      expect(res.status).toBe(301);
      expect(res.headers.get("location")).toBe(location);
    }
    // one lookup per slug a minute, and the job's own 404 lookup is skipped
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toMatch(/\/api\/v1\/public\/domains\/by-slug\/acme$/);
  });

  it("keeps the slug URL when the tenant has no verified domain", async () => {
    vi.stubGlobal("fetch", domainFor(null, 404));
    const res = await middleware(req("/c/acme/jobs/nope"));
    expect(res.status).toBe(404);
    expect(res.headers.get("location")).toBeNull();
  });

  it("leaves previews, client-side navigations and prefetches on the instance host", async () => {
    const fetchMock = domainFor("careers.acme.com");
    vi.stubGlobal("fetch", fetchMock);
    const preview = await middleware(req("/c/acme/jobs/draft?preview=tok"));
    expect(preview.headers.get("location")).toBeNull();
    for (const header of ["rsc", "next-router-prefetch"]) {
      const res = await middleware(
        new NextRequest("http://ganek.test/c/acme", { headers: { [header]: "1" } }),
      );
      expect(res.headers.get("location")).toBeNull();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails open, uncached, when the lookup errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    expect((await middleware(req("/c/acme"))).headers.get("location")).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));
    expect((await middleware(req("/c/acme"))).headers.get("location")).toBeNull();
    vi.stubGlobal("fetch", domainFor("careers.acme.com"));
    expect((await middleware(req("/c/acme"))).status).toBe(301);
  });

  it("never redirects a slug URL to the host it is already on", async () => {
    // the domain's own resolve failed (fail open), so the request is served
    // like the instance host; the by-slug answer is that same host
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/public/domains/resolve")) throw new Error("ECONNREFUSED");
        return Response.json({ slug: "acme", domain: "careers.acme.com" });
      }),
    );
    const res = await middleware(hostReq("careers.acme.com", "/c/acme"));
    expect(res.headers.get("location")).toBeNull();
  });
});

function resolveHost(slug: string, domain: string | null) {
  return vi.fn(async (url: string) => {
    if (url.includes("/public/domains/resolve")) return Response.json({ slug, domain });
    return new Response("{}", { status: 200 });
  });
}

describe("tenant subdomains", () => {
  it("serves the tenant's careers page on its subdomain", async () => {
    vi.stubGlobal("fetch", resolveHost("acme", "acme.ganek.io"));
    const res = await middleware(hostReq("acme.ganek.io", "/jobs/dev"));
    expect(res.status).toBe(200);
    expect(res.headers.get("x-middleware-rewrite")).toBe("https://acme.ganek.io/c/acme/jobs/dev");
  });

  it("301s the subdomain's careers pages to the verified custom domain, query kept", async () => {
    vi.stubGlobal("fetch", resolveHost("acme", "careers.acme.com"));
    const cases: [string, string][] = [
      ["/?src=x", "https://careers.acme.com/?src=x"],
      ["/jobs/dev", "https://careers.acme.com/jobs/dev"],
      ["/privacy/", "https://careers.acme.com/privacy"],
    ];
    for (const [path, location] of cases) {
      const res = await middleware(hostReq("acme.ganek.io", path));
      expect(res.status).toBe(301);
      expect(res.headers.get("location")).toBe(location);
    }
  });

  it("keeps token pages, previews and client-side navigations on the subdomain", () => {
    const tenant = { slug: "acme", domain: "careers.acme.com" };
    const at = (path: string, headers: Record<string, string> = {}) =>
      canonicalHostRedirectUrl(hostReq("acme.ganek.io", path, headers), "acme.ganek.io", tenant);
    expect(at("/quiz/tok")).toBeNull();
    expect(at("/c/acme")).toBeNull();
    expect(at("/jobs/draft?preview=tok")).toBeNull();
    expect(at("/", { rsc: "1" })).toBeNull();
    expect(at("/", { "next-router-prefetch": "1" })).toBeNull();
    // already on the canonical host, or no canonical host known
    expect(
      canonicalHostRedirectUrl(hostReq("careers.acme.com", "/"), "careers.acme.com", tenant),
    ).toBeNull();
    expect(
      canonicalHostRedirectUrl(hostReq("acme.ganek.io", "/"), "acme.ganek.io", {
        slug: "acme",
        domain: null,
      }),
    ).toBeNull();
  });
});
