"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { JobForm } from "@/components/JobForm";
import { StatusPill } from "@/components/JobStatus";
import { JobStatusCard } from "@/components/JobStatusCard";
import { api, companyApi, type JobOut, type ScreeningQuestion } from "@/lib/api";

export default function EditJobPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<JobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  // for "Reset to company defaults" in the screening editor; a failed fetch
  // only hides that button
  const [defaults, setDefaults] = useState<ScreeningQuestion[] | undefined>(undefined);
  useEffect(() => {
    companyApi
      .summary()
      .then((summary) => setDefaults(summary.screening_questions))
      .catch(() => setDefaults(undefined));
  }, []);

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
          /{" "}
          <Link href={`/admin/jobs/${job.id}`} className="hover:text-accent">
            {job.slug}
          </Link>{" "}
          / edit
        </p>
        <div className="mt-1.5 flex items-center gap-2.5">
          <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">
            {job.title}
          </h1>
          <StatusPill status={job.status} />
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <JobForm
        initial={job}
        defaultScreening={defaults}
        submitLabel="Save changes"
        onSubmit={async (values) => {
          await api.jobs.update(job.id, values);
          router.push(`/admin/jobs/${job.id}`);
        }}
        rail={<JobStatusCard job={job} onError={setError} onChanged={reload} />}
      />
    </section>
  );
}
