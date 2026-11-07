import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jobLookupPath, middleware } from "./middleware";

function req(path: string, cookie?: string): NextRequest {
  return new NextRequest(`http://ganek.test${path}`, {
    headers: cookie ? { cookie } : undefined,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
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

  it("is scoped to /admin, /review and the public job pages by its matcher", async () => {
    const { config } = await import("./middleware");
    expect(config.matcher).toEqual([
      "/admin/:path*",
      "/review/:path*",
      "/jobs/:jobSlug",
      "/c/:slug/jobs/:jobSlug",
    ]);
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
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
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
