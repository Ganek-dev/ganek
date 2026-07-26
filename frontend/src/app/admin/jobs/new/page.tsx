"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { JobForm } from "@/components/JobForm";
import { api } from "@/lib/api";

export default function NewJobPage() {
  const router = useRouter();
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
        submitLabel="Create job"
        onSubmit={async (values) => {
          await api.jobs.create(values);
          router.push("/admin/jobs");
        }}
      />
    </section>
  );
}
