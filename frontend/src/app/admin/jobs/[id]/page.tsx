"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ExternalLink, Pencil } from "lucide-react";

import { ScoreChip, StagePill } from "@/components/ApplicantChips";
import { CopyButton } from "@/components/CopyButton";
import { AssessmentChip, StatusPill } from "@/components/JobStatus";
import { JobStatusCard } from "@/components/JobStatusCard";
import { QuizPreviewPanel } from "@/components/QuizPreviewPanel";
import {
  api,
  applications,
  companyApi,
  type ApplicationOut,
  type ApplicationStage,
  type CompanyAdmin,
  type JobOut,
  type JobStats,
} from "@/lib/api";
import { careersDisplay, careersUrl } from "@/lib/careers";
import { relativeTime } from "@/lib/time";

/** Job overview (spec "07b"): what a job is doing, who applied, and the
 * assessment candidates get. Counts only: nothing here ranks, passes or
 * recommends (rule 5). The editor lives under /edit. */

const CANDIDATE_LIMIT = 50;

const STAGE_ORDER: ApplicationStage[] = [
  "new",
  "screening",
  "interview",
  "offer",
  "hired",
  "rejected",
  "withdrawn",
];

const STAGE_LABEL: Record<ApplicationStage, string> = {
  new: "New",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** Header meta line: where the job is in its life, in one sentence. */
export function lifecycleLine(job: JobOut, daysOpen: number | null): string {
  if (job.status === "draft" || job.published_at === null) return "Draft, not published";
  if (job.status === "closed") {
    return daysOpen === null ? "Closed" : `Closed after ${plural(daysOpen, "day")}`;
  }
  const since = `Live since ${shortDate(job.published_at)}`;
  if (daysOpen === null || daysOpen === 0) return `${since} · today`;
  return `${since} · ${plural(daysOpen, "day")} open`;
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card px-4 py-3.5">
      <p className="text-xs text-g500">{label}</p>
      <p className="mt-1.5 font-heading text-[26px] leading-none font-semibold">{value}</p>
      {hint ? <p className="mt-1.5 font-mono text-[11px] text-g500">{hint}</p> : null}
    </div>
  );
}

function quizTile(job: JobOut, stats: JobStats): { value: string; hint: string } {
  const { attempts_started: started, attempts_completed: completed, median_score } = stats.quiz;
  if (started === 0) {
    return { value: "-", hint: job.quiz_config.enabled ? "no attempts yet" : "assessment off" };
  }
  const median = median_score === null ? "" : ` · median ${Math.round(median_score * 100)}%`;
  return {
    value: `${Math.round((completed / started) * 100)}%`,
    hint: `${completed} of ${started} started${median}`,
  };
}

function FlagsDot({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span
      role="img"
      aria-label={plural(count, "integrity flag")}
      className="inline-block h-2 w-2 rounded-full bg-orange-500"
    />
  );
}

export default function JobOverviewPage() {
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<JobOut | null>(null);
  const [stats, setStats] = useState<JobStats | null>(null);
  const [company, setCompany] = useState<CompanyAdmin | null>(null);
  const [candidates, setCandidates] = useState<ApplicationOut[] | null>(null);
  const [stage, setStage] = useState<ApplicationStage | "all">("all");
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api.jobs
      .get(params.id)
      .then(setJob)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load job"),
      );
    api.jobs.stats(params.id).then(setStats).catch(() => setStats(null));
    companyApi
      .get()
      .then(setCompany)
      .catch(() => setCompany(null));
  }, [params.id]);

  useEffect(reload, [reload]);

  useEffect(() => {
    applications
      .list({
        job_id: params.id,
        stage: stage === "all" ? undefined : stage,
        limit: CANDIDATE_LIMIT,
      })
      .then((page) => setCandidates(page.items))
      .catch(() => setCandidates([]));
  }, [params.id, stage]);

  if (error && !job) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        {error}
      </p>
    );
  }
  if (!job) {
    return (
      <section aria-busy="true" className="space-y-4">
        <div className="h-8 w-64 animate-pulse rounded-sm bg-muted-fill" />
        <div className="h-24 animate-pulse rounded-lg bg-muted-fill" />
        <div className="h-96 animate-pulse rounded-lg bg-muted-fill" />
      </section>
    );
  }

  const live = job.status === "published";
  const jobUrl = company ? `${careersUrl(company.mode, company.slug)}/jobs/${job.slug}` : null;
  const jobDisplay = company
    ? `${careersDisplay(company.mode, company.slug)}/jobs/${job.slug}`
    : null;
  const total = stats?.applications.total ?? 0;
  const quiz = stats ? quizTile(job, stats) : null;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[11.5px] text-g500">
            <Link href="/admin/jobs" className="hover:text-accent">
              Jobs
            </Link>{" "}
            / {job.slug}
          </p>
          <div className="mt-1.5 flex items-center gap-2.5">
            <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">
              {job.title}
            </h1>
            <StatusPill status={job.status} />
          </div>
          <p className="mt-1.5 font-mono text-[11.5px] text-g500">
            {lifecycleLine(job, stats?.days_open ?? null)}
          </p>
        </div>
        <Link
          href={`/admin/jobs/${job.id}/edit`}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-edge bg-surface px-3 text-[13.5px] font-medium text-g700 hover:bg-muted-fill"
        >
          <Pencil aria-hidden className="h-[14px] w-[14px]" />
          Edit
        </Link>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <div className="card flex flex-wrap items-center gap-3 px-4 py-3">
        {live && jobUrl && jobDisplay ? (
          <>
            <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-g700">
              {jobDisplay}
            </span>
            <CopyButton text={jobUrl} label="Copy job URL" />
            <a
              href={jobUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-7 items-center gap-1 rounded-sm border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
            >
              Open
              <ExternalLink aria-hidden className="h-3 w-3" />
            </a>
          </>
        ) : (
          <span className="font-mono text-[12.5px] text-g500">
            {live ? "Public link loads with the company" : "Publish to get a public link"}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile
          label="Applications · 30d"
          value={stats ? String(stats.last_30_days) : "-"}
          hint={
            stats
              ? `${total} all time${stats.applications.new > 0 ? ` · +${stats.applications.new} new` : ""}`
              : undefined
          }
        />
        <Tile label="Quiz completion" value={quiz?.value ?? "-"} hint={quiz?.hint} />
        <Tile label="Views · 30d" value="-" hint="not counted yet" />
        <Tile
          label="Days open"
          value={stats?.days_open === null || stats?.days_open === undefined ? "-" : String(stats.days_open)}
          hint={job.published_at ? `since ${shortDate(job.published_at)}` : "not published"}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="card overflow-visible">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-divider px-4 py-3">
            <span className="font-heading text-[15px] font-semibold">Pipeline</span>
            <div className="flex flex-wrap gap-1.5">
              <StageButton
                label={`All · ${total}`}
                active={stage === "all"}
                onClick={() => setStage("all")}
              />
              {STAGE_ORDER.filter((value) => (stats?.by_stage[value] ?? 0) > 0).map((value) => (
                <StageButton
                  key={value}
                  label={`${STAGE_LABEL[value]} · ${stats?.by_stage[value] ?? 0}`}
                  active={stage === value}
                  onClick={() => setStage(value)}
                />
              ))}
            </div>
          </div>
          {candidates === null ? (
            <div aria-busy="true" className="space-y-2 p-4">
              {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-md bg-muted-fill" />
              ))}
            </div>
          ) : candidates.length === 0 ? (
            <p className="px-4 py-6 text-sm text-g500">
              {stage === "all" ? "No candidates yet." : "No candidates in this stage."}
            </p>
          ) : (
            <table className="w-full text-[13.5px]">
              <thead>
                <tr className="border-b border-divider text-left text-[12.5px] font-medium text-g500">
                  <th className="h-9 px-4 font-medium">Candidate</th>
                  <th className="h-9 px-3 font-medium">Stage</th>
                  <th className="h-9 px-3 font-medium">Score</th>
                  <th className="h-9 px-3 font-medium">Applied</th>
                  <th className="h-9 px-3 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((app) => (
                  <tr
                    key={app.id}
                    className="border-b border-divider last:border-b-0 hover:bg-hover-fill"
                  >
                    <td className="px-4 py-2.5 align-middle">
                      <span className="flex items-center gap-2">
                        <Link
                          href={`/admin/applicants?job=${job.id}&selected=${app.id}`}
                          className="font-medium hover:text-accent"
                        >
                          {app.candidate.name}
                        </Link>
                        <FlagsDot count={app.quiz_attempt?.integrity.flags?.length ?? 0} />
                      </span>
                    </td>
                    <td className="px-3 py-2.5 align-middle whitespace-nowrap">
                      <StagePill stage={app.stage} />
                    </td>
                    <td className="px-3 py-2.5 align-middle whitespace-nowrap">
                      <ScoreChip result={app.quiz_attempt} />
                    </td>
                    <td className="px-3 py-2.5 align-middle font-mono text-xs whitespace-nowrap text-g500">
                      {relativeTime(app.created_at)}
                    </td>
                    <td className="px-3 py-2.5 align-middle whitespace-nowrap">
                      {app.source ? (
                        <span className="inline-flex h-[19px] items-center rounded-[6px] bg-muted-fill px-2 font-mono text-[10.5px] text-g600">
                          {app.source}
                        </span>
                      ) : (
                        <span className="font-mono text-xs text-g400">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="border-t border-divider px-4 py-2.5">
            <Link
              href={`/admin/applicants?job=${job.id}`}
              className="text-[12.5px] font-medium text-accent hover:underline"
            >
              All {plural(total, "candidate")}
            </Link>
          </div>
        </div>

        <div className="space-y-5">
          <JobStatusCard job={job} onError={setError} onChanged={reload} />
          <div className="card px-5 py-[18px]">
            <div className="flex items-center justify-between">
              <span className="font-heading text-[15px] font-semibold">Assessment</span>
              <Link
                href={`/admin/jobs/${job.id}/edit`}
                className="text-[12.5px] font-medium text-accent hover:underline"
              >
                Configure
              </Link>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <AssessmentChip job={job} />
              {job.quiz_config.questionnaire_id ? (
                <Link
                  href={`/admin/questionnaires/${job.quiz_config.questionnaire_id}`}
                  className="font-mono text-[11px] text-g600 hover:text-accent"
                >
                  questionnaire
                </Link>
              ) : null}
            </div>
          </div>
          <QuizPreviewPanel jobId={job.id} />
        </div>
      </div>
    </section>
  );
}

function StageButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex h-7 items-center rounded-full px-[11px] text-[12.5px] font-medium ${
        active
          ? "bg-inverse text-inverse-foreground"
          : "border border-edge bg-surface text-g700 hover:border-g400"
      }`}
    >
      {label}
    </button>
  );
}
