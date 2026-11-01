import type { MetadataRoute } from "next";

import { fetchInstanceInfo } from "@/lib/public-api";
import { publicBaseUrl } from "@/lib/site";

export default async function robots(): Promise<MetadataRoute.Robots> {
  const { demo } = await fetchInstanceInfo();
  if (demo) {
    // a demo instance's vacancies are fictional: keep every page out of search
    return { rules: [{ userAgent: "*", disallow: "/" }] };
  }
  return {
    rules: [
      {
        userAgent: "*",
        // Admin plus every tokened candidate surface - those URLs are
        // capability links and must never end up in a search index.
        disallow: [
          "/admin",
          "/application/",
          "/interview/",
          "/invite/",
          "/login",
          "/review",
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
