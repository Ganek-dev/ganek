"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { MoreHorizontal, Plus, Search } from "lucide-react";

import { api, stats, type JobOut, type JobStatus } from "@/lib/api";

/** Admin jobs table, screen 07: search + status pills, role with tag chips,
 * status badge, applicants with "+N new" accent, assessment chip, posted
 * date and a per-row actions menu. */

const STATUS_PILL: Record<JobStatus, string> = {
  draft: "border-edge bg-muted-fill text-g600",
  published:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  closed:
    "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
};

type JobFilter = "all" | JobStatus;

const FILTERS: { value: JobFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "published", label: "Open" },
  { value: "draft", label: "Draft" },
  { value: "closed", label: "Closed" },
];

interface ApplicantCounts {
  applications: number;
  new: number;
}

function AssessmentChip({ job }: { job: JobOut }) {
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

function RowMenu({
  job,
  open,
  onToggle,
  onAction,
}: {
  job: JobOut;
  open: boolean;
  onToggle: () => void;
  onAction: (action: () => Promise<unknown>) => void;
}) {
  return (
    <div className="relative inline-block">
      <button
        type="button"
        aria-label={`Actions for ${job.title}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onToggle}
        className="inline-flex h-[30px] w-[30px] items-center justify-center rounded-sm text-g500 hover:bg-muted-fill"
      >
        <MoreHorizontal aria-hidden className="h-4 w-4" />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute top-full right-0 z-10 mt-1 w-40 rounded-md border border-edge bg-surface py-1 text-left shadow-lg"
        >
          <Link
            role="menuitem"
            href={`/admin/jobs/${job.id}`}
            className="block px-3 py-1.5 text-[13px] hover:bg-muted-fill"
          >
            Edit
          </Link>
          {job.status !== "published" ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => onAction(() => api.jobs.publish(job.id))}
              className="block w-full px-3 py-1.5 text-left text-[13px] hover:bg-muted-fill"
            >
              Publish
            </button>
          ) : (
            <button
              type="button"
              role="menuitem"
              onClick={() => onAction(() => api.jobs.close(job.id))}
              className="block w-full px-3 py-1.5 text-left text-[13px] hover:bg-muted-fill"
            >
              Close
            </button>
          )}
          {job.status === "draft" ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => onAction(() => api.jobs.delete(job.id))}
              className="block w-full px-3 py-1.5 text-left text-[13px] text-red-600 hover:bg-muted-fill dark:text-red-400"
            >
              Delete
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobOut[] | null>(null);
  const [applicants, setApplicants] = useState<Record<string, ApplicantCounts> | null>(null);
  const [filter, setFilter] = useState<JobFilter>("all");
  const [query, setQuery] = useState("");
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api.jobs
      .list()
      .then(setJobs)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load jobs"),
      );
    stats
      .overview()
      .then((overview) =>
        setApplicants(
          Object.fromEntries(
            overview.per_job.map((row) => [
              row.job_id,
              { applications: row.applications, new: row.new },
            ]),
          ),
        ),
      )
      .catch(() => setApplicants(null));
  }, []);

  useEffect(reload, [reload]);

  useEffect(() => {
    if (openMenuId === null) return;
    const close = () => setOpenMenuId(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenuId]);

  async function act(action: () => Promise<unknown>) {
    setError(null);
    setOpenMenuId(null);
    try {
      await action();
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    }
  }

  const counts =
    jobs === null
      ? null
      : {
          all: jobs.length,
          published: jobs.filter((job) => job.status === "published").length,
          draft: jobs.filter((job) => job.status === "draft").length,
          closed: jobs.filter((job) => job.status === "closed").length,
        };

  const visible =
    jobs === null
      ? null
      : jobs.filter((job) => {
          if (filter !== "all" && job.status !== filter) return false;
          if (query.trim() === "") return true;
          const needle = query.trim().toLowerCase();
          return (
            job.title.toLowerCase().includes(needle) ||
            job.tags.some((tag) => tag.toLowerCase().includes(needle))
          );
        });

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-heading text-2xl font-semibold tracking-[-0.01em]">Jobs</h1>
        <Link
          href="/admin/jobs/new"
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-inverse pr-3 pl-2 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94]"
        >
          <Plus aria-hidden className="h-[15px] w-[15px]" />
          Create job
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-[280px]">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-[11px] h-[15px] w-[15px] -translate-y-1/2 text-g400"
          />
          <input
            type="text"
            aria-label="Search jobs"
            placeholder="Search jobs…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-[34px] w-full rounded-md border border-edge bg-surface pr-3 pl-[34px] text-[13.5px] outline-none focus:border-g400"
          />
        </div>
        <div className="flex gap-1.5">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={filter === option.value}
              onClick={() => setFilter(option.value)}
              className={`inline-flex h-7 items-center rounded-full px-[11px] text-[12.5px] font-medium ${
                filter === option.value
                  ? "bg-inverse text-inverse-foreground"
                  : "border border-edge bg-surface text-g700 hover:border-g400"
              }`}
            >
              {option.label}
              {counts !== null ? ` · ${counts[option.value]}` : ""}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {visible === null ? (
        <div aria-busy="true" className="space-y-2">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-muted-fill" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <p className="text-sm text-g500">
          {jobs !== null && jobs.length > 0 ? (
            "No jobs match."
          ) : (
            <>
              No jobs yet —{" "}
              <Link href="/admin/jobs/new" className="text-accent underline">
                create your first
              </Link>
              .
            </>
          )}
        </p>
      ) : (
        <div className="card overflow-visible">
          <table className="w-full text-[13.5px]">
            <thead>
              <tr className="border-b border-divider text-left text-[12.5px] font-medium text-g500">
                <th className="h-10 px-4 font-medium">Role</th>
                <th className="h-10 px-3 font-medium">Status</th>
                <th className="h-10 px-3 font-medium">Applicants</th>
                <th className="h-10 px-3 font-medium">Assessment</th>
                <th className="h-10 px-3 font-medium">Posted</th>
                <th className="h-10 px-3" />
              </tr>
            </thead>
            <tbody>
              {visible.map((job) => {
                const applicant = applicants?.[job.id];
                return (
                  <tr
                    key={job.id}
                    className="border-b border-divider last:border-b-0 hover:bg-hover-fill"
                  >
                    <td className="px-4 py-3 align-middle">
                      <Link
                        href={`/admin/jobs/${job.id}`}
                        className="text-sm font-semibold hover:text-accent"
                      >
                        {job.title}
                      </Link>
                      {job.tags.length > 0 ? (
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {job.tags.slice(0, 3).map((tag) => (
                            <span
                              key={tag}
                              className="inline-flex h-[19px] items-center rounded-[6px] bg-muted-fill px-2 font-mono text-[10.5px] text-g600"
                            >
                              {tag}
                            </span>
                          ))}
                          {job.tags.length > 3 ? (
                            <span className="inline-flex h-[19px] items-center font-mono text-[10.5px] text-g400">
                              +{job.tags.length - 3}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 align-middle whitespace-nowrap">
                      <span
                        className={`inline-flex h-[21px] items-center rounded-full border px-[9px] text-[11.5px] font-medium ${STATUS_PILL[job.status]}`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className="px-3 py-3 align-middle whitespace-nowrap">
                      <span className="font-mono text-[13px]">
                        {applicant === undefined ? "—" : applicant.applications}
                      </span>
                      {applicant !== undefined && applicant.new > 0 ? (
                        <span className="ml-1.5 font-mono text-[11px] font-semibold text-accent">
                          +{applicant.new} new
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 align-middle whitespace-nowrap">
                      <AssessmentChip job={job} />
                    </td>
                    <td className="px-3 py-3 align-middle font-mono text-xs whitespace-nowrap text-g500">
                      {job.published_at
                        ? new Date(job.published_at).toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                          })
                        : "—"}
                    </td>
                    <td className="px-3 py-3 text-right align-middle">
                      <RowMenu
                        job={job}
                        open={openMenuId === job.id}
                        onToggle={() =>
                          setOpenMenuId((current) => (current === job.id ? null : job.id))
                        }
                        onAction={act}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
