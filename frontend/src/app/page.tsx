import { redirect } from "next/navigation";

import { CompanyHero, JobList, themeStyle } from "@/components/careers";
import { fetchInstanceMode, publicApi } from "@/lib/public-api";

export default async function Home() {
  const mode = await fetchInstanceMode();
  if (mode === "multi") redirect("/admin");

  const page = await publicApi.singleCompanyPage();
  if (page === null) redirect("/setup");

  return (
    <main
      className="mx-auto max-w-3xl space-y-8 px-4 py-12"
      style={themeStyle(page.company)}
    >
      <CompanyHero company={page.company} />
      <JobList jobs={page.jobs} hrefFor={(job) => `/jobs/${job.slug}`} />
    </main>
  );
}
