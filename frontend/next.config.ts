import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
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
    // compose passes VETD_S3_PUBLIC_ENDPOINT_URL as a build arg).
    const cvUploadOrigin = new URL(
      process.env.VETD_S3_PUBLIC_ENDPOINT_URL || "http://localhost:9000",
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
