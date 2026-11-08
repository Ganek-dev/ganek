import type { MetadataRoute } from "next";

import { ROBOTS_DISALLOW } from "@/lib/crawl";
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
        disallow: ROBOTS_DISALLOW,
      },
    ],
    sitemap: `${publicBaseUrl()}/sitemap.xml`,
  };
}
