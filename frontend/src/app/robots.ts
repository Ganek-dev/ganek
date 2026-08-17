import type { MetadataRoute } from "next";

import { publicBaseUrl } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        // Admin plus every tokened candidate surface — those URLs are
        // capability links and must never end up in a search index.
        disallow: [
          "/admin",
          "/application/",
          "/interview/",
          "/invite/",
          "/login",
          "/quiz/",
          "/reset",
          "/setup",
          "/verify",
        ],
      },
    ],
    sitemap: `${publicBaseUrl()}/sitemap.xml`,
  };
}
