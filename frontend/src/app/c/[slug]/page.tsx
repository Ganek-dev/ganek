import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CompanyHero, JobList, themeStyle } from "@/components/careers";
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
      className="mx-auto max-w-3xl space-y-8 px-4 py-12"
      style={themeStyle(page.company)}
    >
      <CompanyHero company={page.company} />
      <JobList jobs={page.jobs} hrefFor={(job) => `/c/${slug}/jobs/${job.slug}`} />
    </main>
  );
}
