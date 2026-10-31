"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { JobForm } from "@/components/JobForm";
import { api, companyApi, type ScreeningQuestion } from "@/lib/api";

export default function NewJobPage() {
  const router = useRouter();
  // the company default screening questions prefill the editor; the server
  // copies them too when a client omits the field, so a failed fetch only
  // costs the prefill
  const [defaults, setDefaults] = useState<ScreeningQuestion[] | null>(null);
  useEffect(() => {
    companyApi
      .summary()
      .then((summary) => setDefaults(summary.screening_questions))
      .catch(() => setDefaults([]));
  }, []);
  if (defaults === null) {
    return (
      <section aria-busy="true" className="space-y-5">
        <div className="h-6 w-40 animate-pulse rounded-md bg-muted-fill" />
        <div className="h-64 animate-pulse rounded-md bg-muted-fill" />
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
          / new
        </p>
        <h1 className="mt-1.5 font-heading text-[22px] font-semibold tracking-[-0.01em]">
          New job
        </h1>
      </div>
      <JobForm
        defaultScreening={defaults}
        submitLabel="Create job"
        onSubmit={async (values) => {
          const created = await api.jobs.create(values);
          router.push(`/admin/jobs/${created.id}`);
        }}
      />
    </section>
  );
}
