"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api, type JobOut, type JobStatus } from "@/lib/api";

const STATUS_STYLES: Record<JobStatus, string> = {
  draft: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  published: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  closed: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api.jobs
      .list()
      .then(setJobs)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load jobs"),
      );
  }, []);

  useEffect(reload, [reload]);

  async function act(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Jobs</h1>
        <Link
          href="/admin/jobs/new"
          className="rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
        >
          New job
        </Link>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {jobs === null ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : jobs.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No jobs yet. Create your first job posting to get started.
        </p>
      ) : (
        <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
          {jobs.map((job) => (
            <li key={job.id} className="flex items-center justify-between gap-4 p-4">
              <div className="min-w-0">
                <Link
                  href={`/admin/jobs/${job.id}`}
                  className="font-medium text-zinc-900 hover:underline dark:text-zinc-50"
                >
                  {job.title}
                </Link>
                <p className="truncate text-sm text-zinc-500">
                  {[job.location || null, job.remote_policy, ...job.tags.slice(0, 4)]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[job.status]}`}
                >
                  {job.status}
                </span>
                {job.status !== "published" ? (
                  <button
                    type="button"
                    onClick={() => act(() => api.jobs.publish(job.id))}
                    className="rounded-md border border-zinc-300 px-2 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    Publish
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => act(() => api.jobs.close(job.id))}
                    className="rounded-md border border-zinc-300 px-2 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    Close
                  </button>
                )}
                {job.status === "draft" ? (
                  <button
                    type="button"
                    onClick={() => act(() => api.jobs.delete(job.id))}
                    className="rounded-md border border-red-300 px-2 py-1 text-sm text-red-700 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
                  >
                    Delete
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
