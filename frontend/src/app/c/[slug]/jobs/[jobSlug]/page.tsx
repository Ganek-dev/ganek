import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ApplyForm } from "@/components/ApplyForm";
import { JobPosting } from "@/components/JobPosting";
import { publicApi } from "@/lib/public-api";

interface Props {
  params: Promise<{ slug: string; jobSlug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug, jobSlug } = await params;
  const [page, job] = await Promise.all([
    publicApi.companyPage(slug),
    publicApi.companyJob(slug, jobSlug),
  ]);
  if (!page || !job) return {};
  return { title: `${job.title} — ${page.company.name}` };
}

export default async function CompanyJobPage({ params }: Props) {
  const { slug, jobSlug } = await params;
  const [page, job] = await Promise.all([
    publicApi.companyPage(slug),
    publicApi.companyJob(slug, jobSlug),
  ]);
  if (!page || !job) notFound();

  return (
    <main className="mx-auto max-w-3xl space-y-10 px-4 py-12">
      <JobPosting company={page.company} job={job} backHref={`/c/${slug}`} />
      <ApplyForm apiBasePath={`/api/v1/public/companies/${slug}/jobs/${job.slug}`} />
    </main>
  );
}
