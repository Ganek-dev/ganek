"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { JobForm } from "@/components/JobForm";
import { api, type JobOut } from "@/lib/api";

export default function EditJobPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<JobOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.jobs
      .get(params.id)
      .then(setJob)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load job"),
      );
  }, [params.id]);

  if (error) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        {error}
      </p>
    );
  }
  if (!job) {
    return <p className="text-sm text-zinc-500">Loading…</p>;
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{job.title}</h1>
        <span className="text-xs text-zinc-500">/{job.slug}</span>
      </div>
      <JobForm
        initial={job}
        submitLabel="Save changes"
        onSubmit={async (values) => {
          await api.jobs.update(job.id, values);
          router.push("/admin/jobs");
        }}
      />
    </section>
  );
}
