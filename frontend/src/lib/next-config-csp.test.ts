import { afterEach, describe, expect, it, vi } from "vitest";

/** CVs upload straight from the browser to a presigned S3 URL, which is a
 * different origin than the app — connect-src must allow it or the PUT is
 * CSP-blocked (the bug: `connect-src 'self'` killed every CV upload). */

async function cspFor(env: Record<string, string | undefined>): Promise<string> {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) vi.stubEnv(key, "");
    else vi.stubEnv(key, value);
  }
  const { default: config } = await import("../../next.config");
  const rules = await config.headers!();
  const header = rules[0].headers.find((h) => h.key === "Content-Security-Policy");
  return header!.value;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Content-Security-Policy connect-src", () => {
  it("allows the default local MinIO origin so CV uploads work out of the box", async () => {
    const csp = await cspFor({ GANEK_S3_PUBLIC_ENDPOINT_URL: undefined });
    expect(csp).toContain("connect-src 'self' http://localhost:9000");
  });

  it("allows the configured public S3 origin", async () => {
    const csp = await cspFor({
      GANEK_S3_PUBLIC_ENDPOINT_URL: "https://uploads.example.com",
    });
    expect(csp).toContain("connect-src 'self' https://uploads.example.com");
  });

  it("normalizes a path-style endpoint down to its origin", async () => {
    const csp = await cspFor({
      GANEK_S3_PUBLIC_ENDPOINT_URL: "https://s3.example.com/ganek-cvs/",
    });
    expect(csp).toContain("connect-src 'self' https://s3.example.com");
    expect(csp).not.toContain("ganek-cvs");
  });
});
