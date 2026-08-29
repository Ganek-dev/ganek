import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "./middleware";

function req(path: string, cookie?: string): NextRequest {
  return new NextRequest(`http://ganek.test${path}`, {
    headers: cookie ? { cookie } : undefined,
  });
}

describe("admin middleware", () => {
  it("redirects cookieless visitors to /login", () => {
    const res = middleware(req("/admin/applicants"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://ganek.test/login");
  });

  it("passes requests that carry a session cookie", () => {
    const res = middleware(req("/admin/applicants", "ganek_session=whatever"));
    expect(res.headers.get("location")).toBeNull();
  });

  it("is scoped to /admin by its matcher", async () => {
    const { config } = await import("./middleware");
    expect(config.matcher).toBe("/admin/:path*");
  });
});
