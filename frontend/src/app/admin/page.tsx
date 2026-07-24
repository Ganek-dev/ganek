"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { stats, type StatsOverview } from "@/lib/api";

const cardCls =
  "rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className={cardCls}>
      <p className="text-sm text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">{value}</p>
      {hint ? <p className="text-xs text-zinc-400">{hint}</p> : null}
    </div>
  );
}

function WeeklyChart({ weekly }: { weekly: StatsOverview["weekly"] }) {
  const max = Math.max(1, ...weekly.map((point) => point.count));
  return (
    <div className={cardCls}>
      <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        Applications per week
      </h2>
      <div className="mt-3 flex h-28 items-end gap-2" role="img" aria-label="Applications per week">
        {weekly.map((point) => (
          <div key={point.week_start} className="flex flex-1 flex-col items-center justify-end gap-1">
            <span className="text-xs text-zinc-500">{point.count > 0 ? point.count : ""}</span>
            <div
              title={`Week of ${point.week_start}: ${point.count}`}
              className="w-full rounded-t bg-zinc-900 dark:bg-zinc-100"
              style={{ height: `${Math.max(4, (point.count / max) * 80)}px` }}
            />
            <span className="text-[10px] text-zinc-400">
              {new Date(point.week_start).toLocaleDateString("en-US", {
                month: "numeric",
                day: "numeric",
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [data, setData] = useState<StatsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    stats
      .overview()
      .then(setData)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load dashboard"),
      );
  }, []);

  if (error) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        {error}
      </p>
    );
  }
  if (!data) {
    return <p className="text-sm text-zinc-500">Loading dashboard…</p>;
  }

  const completionPercent =
    data.quiz.completion_rate === null ? null : Math.round(data.quiz.completion_rate * 100);
  const avgPercent = data.quiz.avg_score === null ? null : Math.round(data.quiz.avg_score * 100);

  return (
    <section className="space-y-4">
      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Dashboard</h1>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Open positions"
          value={String(data.jobs.published)}
          hint={`${data.jobs.draft} draft · ${data.jobs.closed} closed`}
        />
        <StatCard
          label="New applicants"
          value={String(data.applications.new)}
          hint={`${data.applications.total} total`}
        />
        <StatCard
          label="Last 7 days"
          value={String(data.applications.last_7_days)}
          hint="applications received"
        />
        <StatCard
          label="Quiz completion"
          value={completionPercent === null ? "—" : `${completionPercent}%`}
          hint={avgPercent === null ? "no completed quizzes yet" : `avg score ${avgPercent}%`}
        />
      </div>

      <WeeklyChart weekly={data.weekly} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={cardCls}>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Positions</h2>
            <Link href="/admin/jobs" className="text-sm text-zinc-500 underline">
              Manage jobs
            </Link>
          </div>
          {data.per_job.length === 0 ? (
            <p className="mt-2 text-sm text-zinc-500">
              No jobs yet —{" "}
              <Link href="/admin/jobs/new" className="underline">
                create your first
              </Link>
              .
            </p>
          ) : (
            <ul className="mt-2 divide-y divide-zinc-100 dark:divide-zinc-800">
              {data.per_job.map((job) => (
                <li key={job.job_id} className="flex items-center justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <Link
                      href={`/admin/jobs/${job.job_id}`}
                      className="truncate text-sm font-medium text-zinc-900 hover:underline dark:text-zinc-50"
                    >
                      {job.title}
                    </Link>
                    <span className="ml-2 text-xs text-zinc-400">{job.status}</span>
                  </div>
                  <p className="shrink-0 text-sm text-zinc-500">
                    {job.applications} applicant{job.applications === 1 ? "" : "s"}
                    {job.new > 0 ? (
                      <span className="ml-1.5 rounded-full bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900 dark:text-green-200">
                        {job.new} new
                      </span>
                    ) : null}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className={cardCls}>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
              Recent applicants
            </h2>
            <Link href="/admin/applicants" className="text-sm text-zinc-500 underline">
              View all
            </Link>
          </div>
          {data.recent.length === 0 ? (
            <p className="mt-2 text-sm text-zinc-500">No applications yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-zinc-100 dark:divide-zinc-800">
              {data.recent.map((app) => (
                <li key={app.id} className="flex items-center justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-50">
                      {app.candidate_name}
                    </p>
                    <p className="truncate text-xs text-zinc-500">
                      {app.job_title} · {new Date(app.created_at).toLocaleDateString("en-US")}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {app.quiz_score !== null ? (
                      <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                        quiz {Math.round(app.quiz_score * 100)}%
                      </span>
                    ) : null}
                    <span className="text-xs text-zinc-400">{app.stage}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
