import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { notFound } from "next/navigation";

import { ApplyForm } from "@/components/ApplyForm";
import { HowWeHire, JobGone, JobHero, JobPosting } from "@/components/JobPosting";
import { themeStyle } from "@/components/careers";
import { DemoBanner } from "@/components/DemoBanner";
import { PreviewBar } from "@/components/PreviewBar";
import { demoRobots, fetchInstanceInfo, publicApi, resolveJobView } from "@/lib/public-api";
import { resolveSource, websiteHostOf } from "@/lib/source";
import { isPrefetch, shouldCountView, viewHeaders } from "@/lib/views";

interface Props {
  params: Promise<{ slug: string; jobSlug: string }>;
  searchParams: Promise<{
    preview?: string;
    src?: string | string[];
    utm_source?: string | string[];
  }>;
}

const NOINDEX = { robots: { index: false, follow: false } } as const;

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const [{ slug, jobSlug }, { preview }] = await Promise.all([params, searchParams]);
  const [page, { job, previewing }, { demo }] = await Promise.all([
    publicApi.companyPage(slug),
    resolveJobView((token) => publicApi.companyJob(slug, jobSlug, token), preview),
    fetchInstanceInfo(),
  ]);
  if (!page || !job) return {};
  return {
    title: `${job.title} — ${page.company.name}`,
    ...(previewing ? NOINDEX : demoRobots(demo)),
  };
}

export default async function CompanyJobPage({ params, searchParams }: Props) {
  const [{ slug, jobSlug }, query, requestHeaders, cookieStore] = await Promise.all([
    params,
    searchParams,
    headers(),
    cookies(),
  ]);
  const { preview } = query;
  // the company first: the source bucket needs its website host
  const page = await publicApi.companyPage(slug);
  if (!page) notFound();

  // where this visit came from (spec 5.4): src > utm_source > Referer > direct
  const source = resolveSource({
    src: query.src,
    utm_source: query.utm_source,
    referer: requestHeaders.get("referer"),
    websiteHost: websiteHostOf(page.company.website),
  });
  // spec 5.5: only the page render counts a view, and only for a person
  // who is not the signed-in recruiter, not previewing, not prefetching
  const view = shouldCountView({
    userAgent: requestHeaders.get("user-agent"),
    hasSession: cookieStore.has("ganek_session"),
    preview,
    prefetch: isPrefetch(requestHeaders),
  })
    ? viewHeaders(source)
    : undefined;
  const [{ job, previewing }, { demo }] = await Promise.all([
    resolveJobView((token) => publicApi.companyJob(slug, jobSlug, token, view), preview),
    fetchInstanceInfo(),
  ]);
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
      {previewing ? <PreviewBar /> : demo ? <DemoBanner tone="brand" /> : null}
      <JobHero company={page.company} job={job} backHref={`/c/${slug}`} />
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
                apiBasePath={`/api/v1/public/companies/${slug}/jobs/${job.slug}`}
                jobTitle={job.title}
                companyName={page.company.name}
                demo={demo}
                privacyHref={`/c/${slug}/privacy`}
                source={source}
              />
            </section>
          </>
        )}
      </div>
    </main>
  );
}
