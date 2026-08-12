import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ApplyForm } from "@/components/ApplyForm";
import { HowWeHire, JobGone, JobHero, JobPosting } from "@/components/JobPosting";
import { themeStyle } from "@/components/careers";
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
  if (!page) notFound();
  if (!job) {
    // screen 27a: job gone, company still live — themed, with a way back
    return (
      <main style={themeStyle(page.company)}>
        <JobGone
          company={page.company}
          jobsHref={`/c/${slug}`}
          jobCount={page.jobs.length}
        />
      </main>
    );
  }

  return (
    <main
      className="min-h-screen bg-surface text-foreground"
      style={themeStyle(page.company)}
    >
      <JobHero company={page.company} job={job} backHref={`/c/${slug}`} />
      <div className="mx-auto max-w-[720px] px-5 pt-7 pb-10 sm:px-6 sm:pt-9 sm:pb-14">
        <JobPosting company={page.company} job={job} />
        <HowWeHire />
        <a
          href="#apply"
          className="mt-6 flex h-[46px] w-full items-center justify-center rounded-md bg-brand text-[15px] font-semibold text-brand-foreground hover:brightness-[0.94]"
        >
          Apply for this position
        </a>
        <p className="mt-3 text-center font-mono text-[11px] text-g400">
          No account needed · Careers powered by vetd
        </p>
        <section id="apply" className="mt-12 scroll-mt-8">
          <ApplyForm
            apiBasePath={`/api/v1/public/companies/${slug}/jobs/${job.slug}`}
            jobTitle={job.title}
            companyName={page.company.name}
            privacyHref={`/c/${slug}/privacy`}
          />
        </section>
      </div>
    </main>
  );
}
