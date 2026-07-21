"use client";

import { useRouter } from "next/navigation";

import { JobForm } from "@/components/JobForm";
import { api } from "@/lib/api";

export default function NewJobPage() {
  const router = useRouter();
  return (
    <section className="space-y-4">
      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">New job</h1>
      <JobForm
        submitLabel="Create job"
        onSubmit={async (values) => {
          await api.jobs.create(values);
          router.push("/admin/jobs");
        }}
      />
    </section>
  );
}
