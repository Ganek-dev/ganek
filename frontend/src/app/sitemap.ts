import type { MetadataRoute } from "next";

import { fetchInstanceMode, publicApi } from "@/lib/public-api";
import { publicBaseUrl } from "@/lib/site";

// The job list changes at runtime; never freeze this at build time.
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = publicBaseUrl();
  const mode = await fetchInstanceMode();
  // Multi mode has no public tenant enumeration (by design — company slugs
  // are only discoverable via their own links), so there is nothing to list.
  if (mode === "multi") return [];

  const page = await publicApi.singleCompanyPage();
  if (page === null) return [];

  return [
    { url: `${base}/`, changeFrequency: "daily" },
    { url: `${base}/privacy`, changeFrequency: "monthly" },
    ...page.jobs.map((job) => ({
      url: `${base}/jobs/${job.slug}`,
      lastModified: job.published_at ?? undefined,
      changeFrequency: "weekly" as const,
    })),
  ];
}
