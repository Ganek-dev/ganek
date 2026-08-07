"use client";

import {
  Briefcase,
  ClipboardList,
  Inbox,
  LayoutGrid,
  ListChecks,
  LogOut,
  Settings,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Wordmark } from "@/components/Wordmark";
import { api, ApiError, stats, type StatsOverview, type UserOut } from "@/lib/api";

const NAV = [
  { href: "/admin", label: "Dashboard", icon: LayoutGrid, exact: true },
  { href: "/admin/jobs", label: "Jobs", icon: Briefcase },
  { href: "/admin/applicants", label: "Applicants", icon: Inbox },
  { href: "/admin/questions", label: "Questions", icon: ListChecks },
  { href: "/admin/questionnaires", label: "Questionnaires", icon: ClipboardList },
  { href: "/admin/team", label: "Team", icon: Users },
  { href: "/admin/branding", label: "Settings", icon: Settings },
] as const;

function counterFor(label: string, overview: StatsOverview | null): number | null {
  if (!overview) return null;
  if (label === "Jobs") return overview.jobs.published + overview.jobs.draft || null;
  if (label === "Applicants") return overview.applications.new || null;
  return null;
}

/** Dark 224px sidebar shell from the design handoff (screen 06). Constant-dark
 *  in both color modes; active item = accent tint over the sidebar color. */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserOut | null>(null);
  const [overview, setOverview] = useState<StatsOverview | null>(null);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
      });
  }, [router]);
  useEffect(() => {
    stats
      .overview()
      .then(setOverview)
      .catch(() => setOverview(null)); // counters are decoration; never block the shell
  }, [pathname]);

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="h-6 w-32 animate-pulse rounded-md bg-muted-fill" />
      </main>
    );
  }

  const initials = user.email.slice(0, 2).toUpperCase();

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 flex w-56 flex-col bg-sidebar text-sidebar-foreground">
        <div className="px-5 py-5">
          <Wordmark className="text-xl" accentClassName="text-accent-soft" />
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ href, label, icon: Icon, ...item }) => {
            const active =
              "exact" in item && item.exact ? pathname === href : pathname.startsWith(href);
            const counter = counterFor(label, overview);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm ${
                  active
                    ? "font-medium text-accent-soft"
                    : "text-zinc-400 hover:bg-white/5 hover:text-zinc-200"
                }`}
                style={
                  active
                    ? { background: "color-mix(in oklab, var(--accent) 32%, var(--sidebar))" }
                    : undefined
                }
              >
                <Icon size={16} strokeWidth={1.75} aria-hidden />
                <span className="flex-1">{label}</span>
                {counter !== null ? (
                  <span
                    className={`rounded-full px-1.5 py-0.5 font-mono text-[11px] ${
                      active ? "bg-white/15 text-white" : "bg-white/10 text-zinc-300"
                    }`}
                  >
                    {counter}
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-2.5 border-t border-white/10 px-4 py-4">
          <span
            aria-hidden
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-[11px] text-white"
            style={{ background: "color-mix(in oklab, var(--accent) 55%, var(--sidebar))" }}
          >
            {initials}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs text-zinc-400">{user.email}</span>
          <button
            type="button"
            aria-label="Sign out"
            title="Sign out"
            className="rounded-md p-1.5 text-zinc-400 hover:bg-white/10 hover:text-zinc-200"
            onClick={() => {
              void api.logout().then(() => router.replace("/login"));
            }}
          >
            <LogOut size={15} aria-hidden />
          </button>
        </div>
      </aside>
      <div className="ml-56 flex-1 p-7">{children}</div>
    </div>
  );
}
