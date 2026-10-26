import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { CareersFooter, CompanyHero, themeStyle } from "@/components/careers";
import { JobList } from "@/components/careers-list";
import { DemoBanner } from "@/components/DemoBanner";
import { demoRobots, fetchInstanceInfo, publicApi } from "@/lib/public-api";
import { resolveSource, sourceSuffix, websiteHostOf } from "@/lib/source";

interface Props {
  searchParams: Promise<{ src?: string | string[]; utm_source?: string | string[] }>;
}

/** The flagship self-host careers page must carry the company's identity,
 * not the generic Ganek title (M5.7 H5 item 16). */
export async function generateMetadata(): Promise<Metadata> {
  const { mode, demo } = await fetchInstanceInfo();
  if (mode === "multi") return {};
  const page = await publicApi.singleCompanyPage();
  if (page === null) return {};
  return {
    title: `${page.company.name} — Careers`,
    description: page.company.description || `Open positions at ${page.company.name}`,
    ...demoRobots(demo),
  };
}

export default async function Home({ searchParams }: Props) {
  const { mode, demo } = await fetchInstanceInfo();
  if (mode === "multi") redirect("/admin");

  const page = await publicApi.singleCompanyPage();
  if (page === null) redirect("/setup");
  const [query, requestHeaders] = await Promise.all([searchParams, headers()]);
  // where this visit came from; carried to the job links (spec 5.4)
  const source = resolveSource({
    src: query.src,
    utm_source: query.utm_source,
    referer: requestHeaders.get("referer"),
    websiteHost: websiteHostOf(page.company.website),
  });

  return (
    <main
      className="min-h-screen bg-surface text-foreground"
      style={themeStyle(page.company)}
    >
      {demo ? <DemoBanner tone="brand" /> : null}
      <CompanyHero company={page.company} jobCount={page.jobs.length} />
      <section className="mx-auto max-w-[720px] px-5 pt-[18px] pb-8 sm:px-6 sm:pt-8 sm:pb-12">
        <JobList jobs={page.jobs} hrefPrefix="/jobs" hrefSuffix={sourceSuffix(source)} />
        <CareersFooter privacyHref="/privacy" />
      </section>
    </main>
  );
}
