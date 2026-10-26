import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ApplyForm } from "@/components/ApplyForm";
import { HowWeHire, JobGone, JobHero, JobPosting } from "@/components/JobPosting";
import { themeStyle } from "@/components/careers";
import { DemoBanner } from "@/components/DemoBanner";
import { PreviewBar } from "@/components/PreviewBar";
import { demoRobots, fetchInstanceInfo, publicApi, resolveJobView } from "@/lib/public-api";

interface Props {
  params: Promise<{ jobSlug: string }>;
  searchParams: Promise<{ preview?: string }>;
}

const NOINDEX = { robots: { index: false, follow: false } } as const;

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const [{ jobSlug }, { preview }] = await Promise.all([params, searchParams]);
  const [page, { job, previewing }, { demo }] = await Promise.all([
    publicApi.singleCompanyPage(),
    resolveJobView((token) => publicApi.singleCompanyJob(jobSlug, token), preview),
    fetchInstanceInfo(),
  ]);
  if (!page || !job) return {};
  return {
    title: `${job.title} — ${page.company.name}`,
    ...(previewing ? NOINDEX : demoRobots(demo)),
  };
}

export default async function SingleModeJobPage({ params, searchParams }: Props) {
  const [{ jobSlug }, { preview }] = await Promise.all([params, searchParams]);
  const [page, { job, previewing }, { demo }] = await Promise.all([
    publicApi.singleCompanyPage(),
    resolveJobView((token) => publicApi.singleCompanyJob(jobSlug, token), preview),
    fetchInstanceInfo(),
  ]);
  if (!page) notFound();
  if (!job) {
    // screen 27a: job gone, company still live — themed, with a way back
    return (
      <main style={themeStyle(page.company)}>
        <JobGone company={page.company} jobsHref="/" jobCount={page.jobs.length} />
      </main>
    );
  }

  return (
    <main
      className="min-h-screen bg-surface text-foreground"
      style={themeStyle(page.company)}
    >
      {previewing ? <PreviewBar /> : demo ? <DemoBanner tone="brand" /> : null}
      <JobHero company={page.company} job={job} backHref="/" />
      <div className="mx-auto max-w-[720px] px-5 pt-7 pb-10 sm:px-6 sm:pt-9 sm:pb-14">
        <JobPosting company={page.company} job={job} jsonLd={!demo && !previewing} />
        <HowWeHire />
        {previewing ? (
          <p className="mt-6 flex h-[46px] w-full items-center justify-center rounded-md border border-edge font-mono text-[12.5px] text-g500">
            Applications open when the job is published.
          </p>
        ) : (
          <>
            <a
              href="#apply"
              className="mt-6 flex h-[46px] w-full items-center justify-center rounded-md bg-brand text-[15px] font-semibold text-brand-foreground hover:brightness-[0.94]"
            >
              Apply for this position
            </a>
            <p className="mt-3 text-center font-mono text-[11px] text-g400">
              No account needed · Careers powered by Ganek
            </p>
            <section id="apply" className="mt-12 scroll-mt-8">
              <ApplyForm
                apiBasePath={`/api/v1/public/company/jobs/${job.slug}`}
                jobTitle={job.title}
                companyName={page.company.name}
                demo={demo}
                privacyHref="/privacy"
              />
            </section>
          </>
        )}
      </div>
    </main>
  );
}
