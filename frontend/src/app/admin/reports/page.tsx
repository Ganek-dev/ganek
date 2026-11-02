"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { Diagnosis } from "@/components/reports/Diagnosis";
import { Funnel } from "@/components/reports/Funnel";
import { KpiTile } from "@/components/reports/KpiTile";
import { ReportFilters, type JobOption } from "@/components/reports/ReportFilters";
import { ScoreDistribution } from "@/components/reports/ScoreDistribution";
import { SourcesTable } from "@/components/reports/SourcesTable";
import { TimeInStage } from "@/components/reports/TimeInStage";
import { WeeklyChart } from "@/components/reports/WeeklyChart";
import { stats, type CohortKpis, type ReportsOut, type ReportsPeriod } from "@/lib/api";

/** Reports: a cohort of applications (created in the period) followed to
 * where they are now. Medians with their n, no benchmark, no pass line. The
 * filters live in the URL, like the applicants page. */

const PERIODS: ReportsPeriod[] = ["30d", "90d", "12m", "all"];
const DEFAULT_PERIOD: ReportsPeriod = "90d";
const PERIOD_WORDS: Record<ReportsPeriod, string> = {
  "30d": "30 days",
  "90d": "90 days",
  "12m": "12 months",
  all: "all time",
};

const round1 = (n: number) => Number(n.toFixed(1));

function caption(period: ReportsPeriod): string {
  if (period === "all") return "All applications, followed to where they are now.";
  const words = PERIOD_WORDS[period];
  return `Applications created in the last ${words}, followed to where they are now. Compared with the ${words} before.`;
}

function diff(now: number, before: number | undefined): number | null {
  return before === undefined ? null : now - before;
}

function Tiles({ cohort, previous }: { cohort: CohortKpis; previous: CohortKpis | null }) {
  const median = cohort.median_time_to_hire_days;
  const prevMedian = previous?.median_time_to_hire_days ?? null;
  const medianDelta = median !== null && prevMedian !== null ? round1(median - prevMedian) : null;
  const notes = [`n = ${cohort.hires_n}`];
  if (previous && prevMedian === null) notes.push(`previous - (n = ${previous.hires_n})`);
  return (
    <div role="group" aria-label="Headline numbers" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <KpiTile
        label="Applications"
        value={String(cohort.applications)}
        delta={diff(cohort.applications, previous?.applications)}
      />
      <KpiTile
        label="Reached interview"
        value={String(cohort.reached_interview)}
        delta={diff(cohort.reached_interview, previous?.reached_interview)}
      />
      <KpiTile label="Hires" value={String(cohort.hires)} delta={diff(cohort.hires, previous?.hires)} />
      <KpiTile
        label="Median time to hire"
        value={median === null ? "-" : String(round1(median))}
        unit={median === null ? undefined : "days"}
        delta={medianDelta}
        deltaUnit=" d"
        note={notes.join(" · ")}
      />
    </div>
  );
}

function Skeleton() {
  return (
    <div aria-busy="true" className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-[92px] animate-pulse rounded-lg bg-muted-fill" />
        ))}
      </div>
      <div className="h-72 animate-pulse rounded-lg bg-muted-fill" />
      <div className="h-48 animate-pulse rounded-lg bg-muted-fill" />
    </div>
  );
}

type Settled = { key: string; report: ReportsOut } | { key: string; error: string };

function ReportsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const rawPeriod = searchParams.get("period");
  const period = PERIODS.find((p) => p === rawPeriod) ?? DEFAULT_PERIOD;
  const job = searchParams.get("job") || null;
  const key = `${period}|${job ?? ""}`;

  const [settled, setSettled] = useState<Settled | null>(null);
  const [jobs, setJobs] = useState<JobOption[]>([]);

  // The job list is a nicety: if the overview fails the filter keeps "All jobs".
  useEffect(() => {
    let cancelled = false;
    stats
      .overview()
      .then((o) => {
        if (!cancelled) setJobs(o.per_job.map(({ job_id, title, status }) => ({ job_id, title, status })));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // A response for a period or job we have since left is dropped.
  useEffect(() => {
    let cancelled = false;
    stats
      .reports({ period, job_id: job ?? undefined })
      .then((report) => {
        if (!cancelled) setSettled({ key, report });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setSettled({ key, error: err instanceof Error ? err.message : "Failed to load reports" });
      });
    return () => {
      cancelled = true;
    };
  }, [period, job, key]);

  const update = useCallback(
    (change: { period?: ReportsPeriod; job?: string | null }) => {
      const nextPeriod = change.period ?? period;
      const nextJob = change.job === undefined ? job : change.job;
      const qs = new URLSearchParams();
      if (nextPeriod !== DEFAULT_PERIOD) qs.set("period", nextPeriod);
      if (nextJob) qs.set("job", nextJob);
      const query = qs.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, period, job],
  );

  const current = settled && settled.key === key ? settled : null;

  return (
    <section className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="font-heading text-2xl font-semibold tracking-[-0.01em]">Reports</h1>
          <ReportFilters period={period} job={job} jobs={jobs} onChange={update} />
        </div>
        <p className="mt-1.5 text-[11px] text-g500">{caption(period)}</p>
      </div>

      {current === null ? (
        <Skeleton />
      ) : "error" in current ? (
        <p role="alert" className="card px-5 py-4 text-sm" style={{ color: "var(--danger)" }}>
          {current.error}
        </p>
      ) : (
        <>
          <Tiles cohort={current.report.cohort} previous={current.report.previous} />
          <Funnel steps={current.report.funnel} quiz={current.report.quiz}>
            <Diagnosis lines={current.report.diagnosis} />
          </Funnel>
          <TimeInStage rows={current.report.time_in_stage} />
          <SourcesTable rows={current.report.sources} />
          <div className="grid gap-4 lg:grid-cols-2">
            <ScoreDistribution quiz={current.report.quiz_scores} />
            <WeeklyChart weekly={current.report.weekly} period={period} />
          </div>
        </>
      )}
    </section>
  );
}

export default function ReportsPage() {
  return (
    <Suspense>
      <ReportsContent />
    </Suspense>
  );
}
