"use client";

import {
  BarChart3,
  Briefcase,
  ClipboardList,
  Inbox,
  LayoutGrid,
  ListChecks,
  LogOut,
  Menu,
  Settings,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CompanySwitcher } from "@/components/CompanySwitcher";
import { DemoBanner } from "@/components/DemoBanner";
import { ImpersonationBanner } from "@/components/ImpersonationBanner";
import { trialDaysLeft, trialDaysText } from "@/lib/trial";
import { Wordmark } from "@/components/Wordmark";
import {
  api,
  ApiError,
  companyApi,
  stats,
  type PlanOut,
  type StatsOverview,
  type UserOut,
} from "@/lib/api";

const NAV = [
  { href: "/admin", label: "Dashboard", icon: LayoutGrid, exact: true },
  { href: "/admin/jobs", label: "Jobs", icon: Briefcase },
  { href: "/admin/applicants", label: "Applicants", icon: Inbox },
  { href: "/admin/reports", label: "Reports", icon: BarChart3 },
  { href: "/admin/questions", label: "Questions", icon: ListChecks },
  { href: "/admin/questionnaires", label: "Questionnaires", icon: ClipboardList },
  { href: "/admin/team", label: "Team", icon: Users, adminOnly: true },
  { href: "/admin/branding", label: "Settings", icon: Settings, adminOnly: true },
] as const;

function counterFor(label: string, overview: StatsOverview | null): number | null {
  if (!overview) return null;
  if (label === "Jobs") return overview.jobs.published + overview.jobs.draft || null;
  if (label === "Applicants") return overview.applications.new || null;
  return null;
}

/** Dark 224px sidebar shell from the design handoff (screen 06). Constant-dark
 *  in both color modes; active item = accent tint over the sidebar color.
 *  Below md the sidebar becomes a drawer opened from a 52px top bar in the
 *  sidebar colour (design round 3, screens R3 03 and R3 09). */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserOut | null>(null);
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [smtpMissing, setSmtpMissing] = useState(false);
  const [usageWarnings, setUsageWarnings] = useState<string[]>([]);
  const [overPlan, setOverPlan] = useState<PlanOut | null>(null);
  const [trialPlan, setTrialPlan] = useState<PlanOut | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [demo, setDemo] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [navPath, setNavPath] = useState(pathname);
  const menuButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLElement>(null);
  const role = user?.role;

  // following a nav link closes the drawer (state adjusted during render, not in an effect)
  if (navPath !== pathname) {
    setNavPath(pathname);
    setNavOpen(false);
  }

  useEffect(() => {
    if (loadFailed) return; // retry re-arms by flipping this back
    api
      .me()
      .then(setUser)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
          return;
        }
        setLoadFailed(true); // backend down/unreachable: say so, don't skeleton forever
      });
  }, [router, loadFailed]);
  useEffect(() => {
    // a reviewer is 403 on everything under /admin: send them to their shell
    if (user?.role === "reviewer") router.replace("/review");
  }, [user, router]);
  useEffect(() => {
    if (user?.role !== "admin") return;
    companyApi
      .get()
      .then((company) => setSmtpMissing(!company.smtp_configured))
      .catch(() => setSmtpMissing(false)); // the banner is advisory; never block the shell
    companyApi
      .usage()
      .then((usage) => setUsageWarnings(usage.warnings))
      .catch(() => setUsageWarnings([])); // soft banner only
    companyApi
      .plan()
      .then((plan) => {
        setOverPlan(plan.over_limit ? plan : null);
        setTrialPlan(plan.trial_ends_at ? plan : null);
      })
      .catch(() => {
        setOverPlan(null); // soft banners only
        setTrialPlan(null);
      });
  }, [user]);
  useEffect(() => {
    if (!role || role === "reviewer") return;
    api
      .providers()
      .then((p) => setDemo(p.demo === true))
      .catch(() => setDemo(false)); // the strip is advisory; never block the shell
  }, [role]);
  useEffect(() => {
    if (!user || user.role === "reviewer") return;
    stats
      .overview()
      .then(setOverview)
      .catch(() => setOverview(null)); // counters are decoration; never block the shell
  }, [pathname, user]);
  useEffect(() => {
    if (!navOpen) return;
    // move focus into the drawer, close on Escape, keep the page behind it still
    drawer.current?.querySelector<HTMLElement>("a[href]")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setNavOpen(false);
      menuButton.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [navOpen]);

  if (loadFailed) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-6">
        <div className="max-w-[380px] text-center">
          <h1 className="font-heading text-[20px] font-semibold">Can&apos;t reach the backend</h1>
          <p className="mt-2 text-[14px] leading-[21px] text-g600">
            The admin app couldn&apos;t load your session. The API may be restarting -
            check the backend container if this persists.
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

  if (user.role === "reviewer") return null; // redirecting; render no staff chrome

  const initials = user.email.slice(0, 2).toUpperCase();
  const visibleNav = NAV.filter((n) => !("adminOnly" in n) || user.role === "admin");

  const avatarStyle = { background: "color-mix(in oklab, var(--accent) 55%, var(--sidebar))" };

  return (
    <div className="min-h-screen bg-background md:flex">
      <header className="sticky top-0 z-20 flex h-[52px] items-center gap-3 bg-sidebar px-4 text-sidebar-foreground md:hidden">
        <button
          ref={menuButton}
          type="button"
          aria-label="Open navigation"
          aria-expanded={navOpen}
          aria-controls="admin-nav"
          onClick={() => setNavOpen(true)}
          className="-ml-3 inline-flex h-11 w-11 items-center justify-center rounded-md hover:bg-white/10"
        >
          <Menu size={20} aria-hidden />
        </button>
        <Wordmark className="text-[18px]" accentClassName="text-accent-soft" />
        <span
          aria-hidden
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-full font-mono text-[11px] text-white"
          style={avatarStyle}
        >
          {initials}
        </span>
      </header>
      {navOpen ? (
        <div
          aria-hidden
          data-testid="nav-backdrop"
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setNavOpen(false)}
        />
      ) : null}
      <aside
        id="admin-nav"
        ref={drawer}
        aria-label="Admin navigation"
        className={`fixed inset-y-0 left-0 z-40 flex w-56 flex-col bg-sidebar text-sidebar-foreground transition-transform md:z-auto md:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full max-md:invisible"
        }`}
      >
        <div className="flex items-center justify-between px-5 py-5">
          <Wordmark className="text-xl" accentClassName="text-accent-soft" />
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => {
              setNavOpen(false);
              menuButton.current?.focus();
            }}
            className="-mr-2 inline-flex h-11 w-11 items-center justify-center rounded-md text-zinc-400 hover:bg-white/10 hover:text-zinc-200 md:hidden"
          >
            <X size={18} aria-hidden />
          </button>
        </div>
        <CompanySwitcher tone="dark" impersonating={Boolean(user.impersonation_expires_at)} />
        <nav className="flex-1 space-y-0.5 px-3">
          {visibleNav.map(({ href, label, icon: Icon, ...item }) => {
            const active =
              "exact" in item && item.exact ? pathname === href : pathname.startsWith(href);
            const counter = counterFor(label, overview);
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setNavOpen(false)}
                aria-current={active ? "page" : undefined}
                aria-label={
                  label === "Applicants" && counter !== null
                    ? `Applicants, ${counter} new applicants`
                    : undefined
                }
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
                    title={label === "Applicants" ? `${counter} new applicants` : undefined}
                    className={`rounded-full px-1.5 py-0.5 font-mono text-[11px] ${
                      active ? "bg-white/15 text-white" : "bg-white/10 text-zinc-300"
                    }`}
                  >
                    {label === "Applicants" ? `${counter} new` : counter}
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
            style={avatarStyle}
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
      <div className="min-w-0 flex-1 p-4 md:ml-56 md:p-7">
        {user.impersonation_expires_at ? (
          <ImpersonationBanner email={user.email} expiresAt={user.impersonation_expires_at} />
        ) : null}
        {demo ? <DemoBanner /> : null}
        {smtpMissing && !demo ? (
          <div
            role="alert"
            className="mb-5 rounded-md border border-amber-300 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200"
          >
            Email is not configured on this instance - candidates are <b>not</b> receiving
            assessment invites or updates. Set the <code className="font-mono">GANEK_SMTP_*</code>{" "}
            variables, then verify with the test send on the{" "}
            <Link href="/admin/privacy" className="font-medium underline">
              Privacy page under Settings
            </Link>
            .
          </div>
        ) : null}
        {overPlan && overPlan.limits.max_live_jobs !== null ? (
          <div
            role="status"
            data-testid="plan-over-limit"
            className="mb-5 rounded-md border border-amber-300 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200"
          >
            {overPlan.live_jobs} jobs are live and your plan allows{" "}
            {overPlan.limits.max_live_jobs}. Nothing was closed, but publishing and reopening
            jobs wait until fewer than {overPlan.limits.max_live_jobs} are live.
            {overPlan.upgrade_url ? (
              <>
                {" "}
                <a href={overPlan.upgrade_url} className="font-medium underline">
                  Upgrade plan
                </a>
              </>
            ) : null}
          </div>
        ) : null}
        {trialPlan?.trial_ends_at && trialDaysLeft(trialPlan.trial_ends_at) > 0 ? (
          <div
            role="status"
            data-testid="plan-trial"
            className="mb-5 rounded-md border border-edge bg-surface px-4 py-2.5 text-[13px] text-g700"
          >
            Team trial: {trialDaysText(trialDaysLeft(trialPlan.trial_ends_at))} (ends{" "}
            {new Date(trialPlan.trial_ends_at).toLocaleDateString()}). After it you are on
            Free again; no job is closed.
            {role === "admin" && trialPlan.billing_enabled ? (
              <>
                {" "}
                <Link href="/admin/billing" className="font-medium underline">
                  Choose a plan
                </Link>
              </>
            ) : null}
          </div>
        ) : null}
        {usageWarnings.length > 0 ? (
          <div
            role="status"
            className="mb-5 rounded-md border border-amber-300 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200"
          >
            Close to a usage limit: {usageWarnings.join(", ")}. Past a limit, candidates see
            a &quot;try again later&quot; message on apply. Limits are set with the{" "}
            <code className="font-mono">GANEK_QUOTA_*</code> variables.
          </div>
        ) : null}
        {children}
      </div>
    </div>
  );
}
