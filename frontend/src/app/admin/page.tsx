import Link from "next/link";

export default function AdminDashboard() {
  return (
    <section>
      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Dashboard</h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        Manage your <Link href="/admin/jobs" className="underline">job postings</Link>. Applicants
        arrive in M2.
      </p>
    </section>
  );
}
