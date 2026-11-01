"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Plus } from "lucide-react";

import { ActivityPanel, QueuePanel, TodayPanel } from "@/components/DashboardPanels";
import { OnboardingChecklist } from "@/components/OnboardingChecklist";
import { UsageCard } from "@/components/UsageCard";
import { OpenRolesBoard } from "@/components/OpenRolesBoard";
import { stats, type BoardOut, type StatsOverview } from "@/lib/api";

/** Recruiter dashboard: greeting, signal tiles from the board API, the open
 * roles board and recent applicants. Charts live in Reports. */

function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function isoWeek(date: Date): number {
  const utc = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = utc.getUTCDay() || 7;
  utc.setUTCDate(utc.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  return Math.ceil(((utc.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7);
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card px-4 py-3.5">
      <p className="text-xs text-g500">{label}</p>
      <p className="mt-1.5 font-heading text-[26px] leading-none font-semibold">{value}</p>
      {hint ? <p className="mt-1.5 font-mono text-[11px] text-g500">{hint}</p> : null}
    </div>
  );
}

export default function AdminDashboard() {
  const [data, setData] = useState<StatsOverview | null>(null);
  const [board, setBoard] = useState<BoardOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([stats.overview(), stats.board()])
      .then(([overview, boardData]) => {
        setData(overview);
        setBoard(boardData);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load dashboard"),
      );
  }, []);

  if (error) {
    return (
      <p role="alert" className="text-sm" style={{ color: "var(--danger)" }}>
        {error}
      </p>
    );
  }
  if (!data || !board) {
    return (
      <section aria-busy="true" className="space-y-4">
        <div className="h-8 w-64 animate-pulse rounded-sm bg-muted-fill" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="h-[92px] animate-pulse rounded-lg bg-muted-fill" />
          ))}
        </div>
        <div className="h-56 animate-pulse rounded-lg bg-muted-fill" />
      </section>
    );
  }

  const now = new Date();
  const rolesWithLive = board.jobs.filter(
    (job) => Object.values(job.live_by_stage).reduce((sum, n) => sum + n, 0) > 0,
  ).length;
  const closedStillHiring = board.jobs.filter((job) => job.job_status === "closed").length;
  const longestWait = Math.max(0, ...board.jobs.map((job) => job.longest_wait_days ?? 0));

  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-[-0.01em]">
            {greeting(now)}
          </h1>
          <p className="mt-1 font-mono text-xs text-g500">
            {now.toLocaleDateString("en-US", {
              weekday: "short",
              month: "short",
              day: "numeric",
            })}{" "}
            · week {isoWeek(now)}
          </p>
        </div>
        <Link
          href="/admin/jobs/new"
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-inverse pr-3 pl-2 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94]"
        >
          <Plus aria-hidden className="h-[15px] w-[15px]" />
          Create job
        </Link>
      </div>

      <OnboardingChecklist />
      <UsageCard />

      <div role="group" aria-label="Signals" className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard
          label="Active jobs"
          value={String(board.totals.active_jobs)}
          hint={closedStillHiring > 0 ? `${closedStillHiring} closed, still hiring` : undefined}
        />
        <StatCard
          label="Live candidates"
          value={String(board.totals.live)}
          hint={`across ${rolesWithLive} role${rolesWithLive === 1 ? "" : "s"}`}
        />
        <StatCard
          label="Waiting on you"
          value={String(board.totals.waiting_on_team)}
          hint={longestWait > 0 ? `longest ${longestWait} d` : undefined}
        />
        <StatCard
          label="Overdue"
          value={String(board.totals.overdue)}
          hint={`more than ${board.stage_limit_days} days`}
        />
        <StatCard label="New this week" value={String(board.totals.new_7d)} hint="last 7 days" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <TodayPanel />
        <QueuePanel overview={data} />
        <ActivityPanel />
      </div>

      <OpenRolesBoard board={board} />

      <div className="grid grid-cols-1 gap-4">
        <div className="card px-5 py-[18px]">
          <div className="flex items-center justify-between">
            <h2 className="font-heading text-[15px] font-semibold">Recent applicants</h2>
            <Link
              href="/admin/applicants"
              className="text-[13px] text-g500 hover:text-accent hover:underline"
            >
              View all
            </Link>
          </div>
          {data.recent.length === 0 ? (
            <p className="mt-2 text-sm text-g500">No applications yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-divider">
              {data.recent.map((app) => (
                <li key={app.id} className="flex items-center justify-between gap-2 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{app.candidate_name}</p>
                    <p className="truncate text-xs text-g500">
                      {app.job_title} · {new Date(app.created_at).toLocaleDateString("en-US")}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {app.quiz_score !== null ? (
                      <span className="rounded-full bg-muted-fill px-2 py-0.5 font-mono text-[10.5px] font-medium text-g600">
                        quiz {Math.round(app.quiz_score * 100)}%
                      </span>
                    ) : null}
                    <span className="font-mono text-[11px] text-g600">{app.stage}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
