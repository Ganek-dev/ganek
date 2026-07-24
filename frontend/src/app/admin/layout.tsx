"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Wordmark } from "@/components/Wordmark";
import { api, ApiError, type UserOut } from "@/lib/api";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
      });
  }, [router]);

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-zinc-500">
        Loading…
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="flex items-center justify-between border-b border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
        <nav className="flex items-center gap-4">
          <Wordmark className="text-lg text-zinc-900 dark:text-zinc-50" />
          <Link
            href="/admin/jobs"
            className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Jobs
          </Link>
          <Link
            href="/admin/applicants"
            className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Applicants
          </Link>
          <Link
            href="/admin/questions"
            className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Questions
          </Link>
          <Link
            href="/admin/team"
            className="text-sm text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Team
          </Link>
        </nav>
        <div className="flex items-center gap-4 text-sm text-zinc-600 dark:text-zinc-400">
          <Link
            href="/admin/account"
            className="hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            {user.email}
          </Link>
          <button
            type="button"
            className="rounded-md border border-zinc-300 px-2 py-1 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            onClick={() => {
              void api.logout().then(() => router.replace("/login"));
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <div className="p-6">{children}</div>
    </div>
  );
}
