import { redirect } from "next/navigation";

import { CareersFooter, CompanyHero, themeStyle } from "@/components/careers";
import { JobList } from "@/components/careers-list";
import { fetchInstanceMode, publicApi } from "@/lib/public-api";

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
