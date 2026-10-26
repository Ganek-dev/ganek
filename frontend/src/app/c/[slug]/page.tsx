import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";

import { CareersFooter, CompanyHero, themeStyle } from "@/components/careers";
import { JobList } from "@/components/careers-list";
import { DemoBanner } from "@/components/DemoBanner";
import { demoRobots, fetchInstanceInfo, publicApi } from "@/lib/public-api";
import { resolveSource, sourceSuffix, websiteHostOf } from "@/lib/source";

interface Props {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ src?: string | string[]; utm_source?: string | string[] }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const [page, { demo }] = await Promise.all([publicApi.companyPage(slug), fetchInstanceInfo()]);
  if (!page) return {};
  return {
    title: `Careers at ${page.company.name}`,
    description: page.company.description || undefined,
    ...demoRobots(demo),
  };
}

export default async function CompanyCareersPage({ params, searchParams }: Props) {
  const [{ slug }, query, requestHeaders] = await Promise.all([params, searchParams, headers()]);
  const [page, { demo }] = await Promise.all([publicApi.companyPage(slug), fetchInstanceInfo()]);
  if (!page) notFound();
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
        <JobList jobs={page.jobs} hrefPrefix={`/c/${slug}/jobs`} hrefSuffix={sourceSuffix(source)} />
        <CareersFooter privacyHref={`/c/${slug}/privacy`} />
      </section>
    </main>
  );
}
