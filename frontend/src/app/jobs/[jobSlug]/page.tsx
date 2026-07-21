import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { JobPosting } from "@/components/JobPosting";
import { publicApi } from "@/lib/public-api";

interface Props {
  params: Promise<{ jobSlug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { jobSlug } = await params;
  const [page, job] = await Promise.all([
    publicApi.singleCompanyPage(),
    publicApi.singleCompanyJob(jobSlug),
  ]);
  if (!page || !job) return {};
  return { title: `${job.title} — ${page.company.name}` };
}

export default async function SingleModeJobPage({ params }: Props) {
  const { jobSlug } = await params;
  const [page, job] = await Promise.all([
    publicApi.singleCompanyPage(),
    publicApi.singleCompanyJob(jobSlug),
  ]);
  if (!page || !job) notFound();

  return (
    <main className="mx-auto max-w-3xl px-4 py-12">
      <JobPosting company={page.company} job={job} backHref="/" />
    </main>
  );
}
