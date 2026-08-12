import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CareersFooter, CompanyHero, themeStyle } from "@/components/careers";
import { JobList } from "@/components/careers-list";
import { publicApi } from "@/lib/public-api";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const page = await publicApi.companyPage(slug);
  if (!page) return {};
  return {
    title: `Careers at ${page.company.name}`,
    description: page.company.description || undefined,
  };
}

export default async function CompanyCareersPage({ params }: Props) {
  const { slug } = await params;
  const page = await publicApi.companyPage(slug);
  if (!page) notFound();

  return (
    <main
      className="min-h-screen bg-surface text-foreground"
      style={themeStyle(page.company)}
    >
      <CompanyHero company={page.company} jobCount={page.jobs.length} />
      <section className="mx-auto max-w-[720px] px-5 pt-[18px] pb-8 sm:px-6 sm:pt-8 sm:pb-12">
        <JobList jobs={page.jobs} hrefPrefix={`/c/${slug}/jobs`} />
        <CareersFooter privacyHref={`/c/${slug}/privacy`} />
      </section>
    </main>
  );
}
