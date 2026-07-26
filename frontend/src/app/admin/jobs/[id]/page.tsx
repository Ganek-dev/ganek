"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { JobForm } from "@/components/JobForm";
import { QuizPreviewPanel } from "@/components/QuizPreviewPanel";
import { api, type JobOut, type JobStatus } from "@/lib/api";

const STATUS_PILL: Record<JobStatus, string> = {
  draft: "border-edge bg-muted-fill text-g600",
  published:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  closed:
    "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
};

function StatusCard({
  job,
  onError,
  onChanged,
}: {
  job: JobOut;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Action failed");
    }
  }

  return (
    <div className="card px-5 py-[18px]">
      <span className="font-heading text-[15px] font-semibold">Status</span>
      <div className="mt-3 flex items-center justify-between">
        <span
          className={`inline-flex h-[21px] items-center rounded-full border px-[9px] text-[11.5px] font-medium ${STATUS_PILL[job.status]}`}
        >
          {job.status}
        </span>
        {job.status !== "published" ? (
          <button
            type="button"
            onClick={() => act(() => api.jobs.publish(job.id))}
            className="inline-flex h-7 items-center rounded-sm border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
          >
            Publish
          </button>
        ) : (
          <button
            type="button"
            onClick={() => act(() => api.jobs.close(job.id))}
            className="inline-flex h-7 items-center rounded-sm border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
          >
            Close
          </button>
        )}
      </div>
      {job.published_at ? (
        <p className="mt-2.5 font-mono text-[11px] text-g500">
          Live since{" "}
          {new Date(job.published_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </p>
      ) : null}
    </div>
  );
}

export default function EditJobPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<JobOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api.jobs
      .get(params.id)
      .then(setJob)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load job"),
      );
  }, [params.id]);

  useEffect(reload, [reload]);

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
        <div className="h-96 animate-pulse rounded-lg bg-muted-fill" />
      </section>
    );
  }

  return (
    <section className="space-y-5">
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
          <span
            className={`inline-flex h-[21px] items-center rounded-full border px-[9px] text-[11.5px] font-medium ${STATUS_PILL[job.status]}`}
          >
            {job.status}
          </span>
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <JobForm
        initial={job}
        submitLabel="Save changes"
        onSubmit={async (values) => {
          await api.jobs.update(job.id, values);
          router.push("/admin/jobs");
        }}
        rail={<StatusCard job={job} onError={setError} onChanged={reload} />}
      />
      <QuizPreviewPanel jobId={job.id} />
    </section>
  );
}
