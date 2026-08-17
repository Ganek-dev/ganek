import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { CareersFooter, CompanyHero, themeStyle } from "@/components/careers";
import { JobList } from "@/components/careers-list";
import { fetchInstanceMode, publicApi } from "@/lib/public-api";

/** The flagship self-host careers page must carry the company's identity,
 * not the generic Vetd title (M5.7 H5 item 16). */
export async function generateMetadata(): Promise<Metadata> {
  const mode = await fetchInstanceMode();
  if (mode === "multi") return {};
  const page = await publicApi.singleCompanyPage();
  if (page === null) return {};
  return {
    title: `${page.company.name} — Careers`,
    description: page.company.description || `Open positions at ${page.company.name}`,
  };
}

export default async function Home() {
  const mode = await fetchInstanceMode();
  if (mode === "multi") redirect("/admin");

  const page = await publicApi.singleCompanyPage();
  if (page === null) redirect("/setup");

  return (
    <main
      className="min-h-screen bg-surface text-foreground"
      style={themeStyle(page.company)}
    >
      <CompanyHero company={page.company} jobCount={page.jobs.length} />
      <section className="mx-auto max-w-[720px] px-5 pt-[18px] pb-8 sm:px-6 sm:pt-8 sm:pb-12">
        <JobList jobs={page.jobs} hrefPrefix="/jobs" />
        <CareersFooter privacyHref="/privacy" />
      </section>
    </main>
  );
}
