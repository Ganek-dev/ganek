import type { JobOut, JobStatus } from "@/lib/api";

/** Status pill classes and the assessment chip shared by the jobs table
 * (screen 07), the job overview and the editor. */

export const STATUS_PILL: Record<JobStatus, string> = {
  draft: "border-edge bg-muted-fill text-g600",
  published:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  closed:
    "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
};

export function StatusPill({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-flex h-[21px] items-center rounded-full border px-[9px] text-[11.5px] font-medium ${STATUS_PILL[status]}`}
    >
      {status}
    </span>
  );
}

export function AssessmentChip({ job }: { job: JobOut }) {
  const config = job.quiz_config;
  if (config.enabled) {
    const time =
      config.time_limit_seconds === null ? "per-q" : `${config.time_limit_seconds}s`;
    return (
      <span className="inline-flex h-[21px] items-center gap-1 rounded-full border border-accent/25 bg-accent/10 px-2 font-mono text-[11px] text-accent">
        {config.question_count}q · {time}
      </span>
    );
  }
  if (job.status === "published") {
    return (
      <span className="inline-flex h-[21px] items-center rounded-full border border-amber-200 bg-amber-50 px-2 font-mono text-[11px] text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
        no quiz yet
      </span>
    );
  }
  return (
    <span className="inline-flex h-[21px] items-center rounded-full border border-edge px-2 font-mono text-[11px] text-g500">
      assessment off
    </span>
  );
}
