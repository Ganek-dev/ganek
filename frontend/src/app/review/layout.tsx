"use client";

import { ChevronDown, LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Wordmark } from "@/components/Wordmark";
import { api, ApiError, companyApi, type UserOut } from "@/lib/api";

/** Reduced shell for reviewers (scorecards spec 5.2): company name, the
 * "Your candidates" title and an account menu. A staff surface, so no
 * per-company brand vars. A reviewer session is 403 on every staff route,
 * so this shell calls only /auth/me and /company/summary - no stats, no
 * providers, none of the admin layout's banners. */
export default function ReviewLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [company, setCompany] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (loadFailed) return; // retry re-arms by flipping this back
    api
      .me()
      .then((me) => {
        if (me.role !== "reviewer") {
          router.replace("/admin");
          return;
        }
        setUser(me);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
          return;
        }
        setLoadFailed(true);
      });
  }, [router, loadFailed]);
  useEffect(() => {
    if (!user) return;
    companyApi
      .summary()
      .then((summary) => setCompany(summary.name))
      .catch(() => setCompany(null)); // the name is decoration; never block the shell
  }, [user]);

  if (loadFailed) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-6">
        <div className="max-w-[380px] text-center">
          <h1 className="font-heading text-[20px] font-semibold">Can&apos;t reach the backend</h1>
          <p className="mt-2 text-[14px] leading-[21px] text-g600">
            Your session could not be loaded. The API may be restarting - try again in a
            moment.
          </p>
          <button
            type="button"
            onClick={() => setLoadFailed(false)}
            className="mt-5 inline-flex h-9 items-center rounded-md border-[1.5px] border-edge px-4 text-[13.5px] font-semibold hover:border-accent hover:text-accent"
          >
            Retry
          </button>
        </div>
      </main>
    );
  }
  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="h-6 w-32 animate-pulse rounded-md bg-muted-fill" />
      </main>
    );
  }

  const label = user.display_label || user.display_name || user.email;

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-divider bg-surface">
        <div className="mx-auto flex h-14 max-w-[960px] items-center gap-4 px-5">
          <Wordmark className="text-lg" />
          {company ? (
            <span className="truncate text-[13.5px] font-medium text-g600">{company}</span>
          ) : (
            <span aria-hidden className="h-4 w-24 animate-pulse rounded bg-muted-fill" />
          )}
          <Link
            href="/review"
            className="ml-2 text-[13.5px] font-semibold hover:text-accent"
          >
            Your candidates
          </Link>
          <div className="relative ml-auto">
            <button
              type="button"
              aria-expanded={menuOpen}
              aria-haspopup="true"
              onClick={() => setMenuOpen((open) => !open)}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-edge px-3 text-[13px] font-medium hover:bg-muted-fill/50"
            >
              <UserRound size={15} aria-hidden />
              <span className="max-w-[160px] truncate">{label}</span>
              <ChevronDown size={14} aria-hidden />
            </button>
            {menuOpen ? (
              <div className="card absolute right-0 z-10 mt-1.5 flex w-48 flex-col p-1.5">
                <Link
                  href="/review/account"
                  onClick={() => setMenuOpen(false)}
                  className="rounded-md px-2.5 py-2 text-[13px] hover:bg-muted-fill/50"
                >
                  Account
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    void api.logout().then(() => router.replace("/login"));
                  }}
                  className="flex items-center gap-2 rounded-md px-2.5 py-2 text-left text-[13px] hover:bg-muted-fill/50"
                >
                  <LogOut size={14} aria-hidden />
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[960px] px-5 py-7">{children}</main>
    </div>
  );
}
