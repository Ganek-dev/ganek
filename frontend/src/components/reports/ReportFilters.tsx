import { ChevronDown } from "lucide-react";

import type { JobStatus, ReportsPeriod } from "@/lib/api";

export const PERIODS: { value: ReportsPeriod; label: string }[] = [
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "12m", label: "12 months" },
  { value: "all", label: "All time" },
];

export interface JobOption {
  job_id: string;
  title: string;
  status: JobStatus;
}

/** Period segmented control and the job select. Drafts are listed last. */
export function ReportFilters({
  period,
  job,
  jobs,
  onChange,
}: {
  period: ReportsPeriod;
  job: string | null;
  jobs: JobOption[];
  onChange: (change: { period?: ReportsPeriod; job?: string | null }) => void;
}) {
  const ordered = [...jobs.filter((j) => j.status !== "draft"), ...jobs.filter((j) => j.status === "draft")];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        role="radiogroup"
        aria-label="Period"
        className="inline-grid grid-cols-4 gap-0.5 rounded-[10px] bg-muted-fill p-0.5"
      >
        {PERIODS.map((p) => {
          const active = p.value === period;
          return (
            <button
              key={p.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange({ period: p.value })}
              className={`h-7 rounded-lg px-3 text-[12.5px] whitespace-nowrap ${
                active ? "bg-surface font-medium text-strong shadow-(--card-ring)" : "text-g600"
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>
      <div className="relative w-[180px]">
        <select
          aria-label="Job"
          value={job ?? ""}
          onChange={(e) => onChange({ job: e.target.value || null })}
          className="h-8 w-full appearance-none rounded-lg border border-edge bg-surface pr-7 pl-2.5 text-[12.5px] text-g700"
        >
          <option value="">All jobs</option>
          {ordered.map((j) => (
            <option key={j.job_id} value={j.job_id}>
              {j.status === "draft" ? `${j.title} (draft)` : j.status === "closed" ? `${j.title} (closed)` : j.title}
            </option>
          ))}
        </select>
        <ChevronDown aria-hidden className="pointer-events-none absolute top-1/2 right-2 h-3.5 w-3.5 -translate-y-1/2 text-g500" />
      </div>
    </div>
  );
}
