import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // next 16.3's standalone tracer ships only @swc/helpers' cjs/ files while
  // the compiled server requires its esm/ paths at boot — force the whole
  // package in until the tracer is fixed upstream.
  outputFileTracingIncludes: {
    "**": ["./node_modules/.pnpm/@swc+helpers@*/node_modules/@swc/helpers/**"],
  },
  async rewrites() {
    // Proxy API calls so session cookies stay same-origin.
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
  async headers() {
    // Security headers on every server-rendered page. The Content-Security-
    // Policy is deliberately conservative; 'unsafe-inline' on styles is
    // required by Tailwind's runtime and Next's inline style attributes.
    // CVs PUT straight from the browser to a presigned S3 URL, so connect-src
    // must also allow the storage origin (headers are baked at build time —
    // compose passes GANEK_S3_PUBLIC_ENDPOINT_URL as a build arg).
    const cvUploadOrigin = new URL(
      process.env.GANEK_S3_PUBLIC_ENDPOINT_URL || "http://localhost:9000",
    ).origin;
    const csp = [
      "default-src 'self'",
      "img-src 'self' data: https:",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      `connect-src 'self' ${cvUploadOrigin}`,
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ");
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
