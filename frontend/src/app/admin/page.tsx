"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Plus } from "lucide-react";

import { ActivityPanel, QueuePanel, TodayPanel } from "@/components/DashboardPanels";
import { OnboardingChecklist } from "@/components/OnboardingChecklist";
import { stats, type StatsOverview } from "@/lib/api";

/** Recruiter dashboard, screen 06 (D3 scope): greeting, stat cards, score
 * distribution with a pass-line that is VISUALIZATION ONLY, positions and
 * recent applicants. Today panel / tasks / activity land with D7. */

const GREEN = "var(--ok)";
const GREEN_BG = "var(--ok-soft)";
const AMBER = "var(--warn)";
const PASS_LINE = 0.6; // where the dashed "pass" marker is drawn — never a filter

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

function formatMinSec(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function StatCard({
  label,
  value,
  hint,
  valueStyle,
  hintStyle,
}: {
  label: string;
  value: string;
  hint?: string;
  valueStyle?: React.CSSProperties;
  hintStyle?: React.CSSProperties;
}) {
  return (
    <div className="card px-4 py-3.5">
      <p className="text-xs text-g500">{label}</p>
      <p
        className="mt-1.5 font-heading text-[26px] leading-none font-semibold"
        style={valueStyle}
      >
        {value}
      </p>
      {hint ? (
        <p className="mt-1.5 font-mono text-[10.5px] text-g500" style={hintStyle}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function ScoreDistribution({ quiz }: { quiz: StatsOverview["quiz"] }) {
  const dist = quiz.score_distribution.length === 10 ? quiz.score_distribution : Array(10).fill(0);
  const total = dist.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...dist);
  const passCount = dist.slice(6).reduce((a, b) => a + b, 0);
  const passRate = total > 0 ? Math.round((passCount / total) * 100) : null;
  const median = quiz.median_score === null ? null : Math.round(quiz.median_score * 100);
  const avgTime =
    quiz.avg_duration_seconds === null ? null : formatMinSec(quiz.avg_duration_seconds);

  return (
    <div className="card px-5 py-[18px]">
      <div className="flex items-baseline justify-between">
        <h2 className="font-heading text-[15px] font-semibold">Score distribution</h2>
        <span className="font-mono text-[11px] text-g500">
          all assessments · {quiz.attempts_completed} completed
        </span>
      </div>
      {total === 0 ? (
        <p className="mt-4 text-sm text-g500">No completed assessments yet.</p>
      ) : (
        <>
          <div
            role="img"
            aria-label="Score distribution"
            className="relative mt-[18px] flex h-[140px] items-end gap-1.5 border-b border-edge"
          >
            <div
              aria-hidden
              className="absolute -top-1.5 bottom-0 w-[1.5px] bg-accent"
              style={{ left: `${PASS_LINE * 100}%` }}
            />
            <span
              aria-hidden
              className="absolute -top-1.5 font-mono text-[10px] text-accent"
              style={{ left: `calc(${PASS_LINE * 100}% + 6px)` }}
            >
              pass ≥ {PASS_LINE * 100}
            </span>
            {dist.map((count, index) => (
              <div
                key={index}
                title={`${index * 10}–${index * 10 + 10}: ${count}`}
                className="flex-1 rounded-t-[3px]"
                style={{
                  height: count === 0 ? "2px" : `${Math.max(6, (count / max) * 100)}%`,
                  background:
                    index * 0.1 >= PASS_LINE
                      ? "color-mix(in oklab, var(--accent) 55%, var(--surface))"
                      : "var(--muted-fill)",
                }}
              />
            ))}
          </div>
          <div className="mt-1.5 flex justify-between font-mono text-[10px] text-g400">
            <span>0</span>
            <span>20</span>
            <span>40</span>
            <span>60</span>
            <span>80</span>
            <span>100</span>
          </div>
          <div className="mt-3.5 flex gap-5 font-mono text-[11px] text-g600">
            <span>
              median <b className="font-semibold text-strong">{median ?? "—"}</b>
            </span>
            <span>
              pass rate <b className="font-semibold text-strong">{passRate ?? "—"}%</b>
            </span>
            <span>
              avg time <b className="font-semibold text-strong">{avgTime ?? "—"}</b>
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function WeeklyChart({ weekly }: { weekly: StatsOverview["weekly"] }) {
  const max = Math.max(1, ...weekly.map((point) => point.count));
  return (
    <div className="card px-5 py-[18px]">
      <h2 className="font-heading text-[15px] font-semibold">Applications per week</h2>
      <div
        className="mt-3 flex h-28 items-end gap-2"
        role="img"
        aria-label="Applications per week"
      >
        {weekly.map((point) => (
          <div
            key={point.week_start}
            className="flex flex-1 flex-col items-center justify-end gap-1"
          >
            <span className="font-mono text-[10px] text-g500">
              {point.count > 0 ? point.count : ""}
            </span>
            <div
              title={`Week of ${point.week_start}: ${point.count}`}
              className="w-full rounded-t-[3px]"
              style={{
                height: `${Math.max(4, (point.count / max) * 80)}px`,
                background: "color-mix(in oklab, var(--accent) 40%, var(--surface))",
              }}
            />
            <span className="font-mono text-[10px] text-g400">
              {new Date(point.week_start).toLocaleDateString("en-US", {
                month: "numeric",
                day: "numeric",
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [data, setData] = useState<StatsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    stats
      .overview()
      .then(setData)
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
  if (!data) {
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
  const completionPercent =
    data.quiz.completion_rate === null ? null : Math.round(data.quiz.completion_rate * 100);
  const avgPercent = data.quiz.avg_score === null ? null : Math.round(data.quiz.avg_score * 100);
  const medianPercent =
    data.quiz.median_score === null ? null : Math.round(data.quiz.median_score * 100);

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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <TodayPanel />
        <QueuePanel overview={data} />
        <ActivityPanel />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard
          label="Active jobs"
          value={String(data.jobs.published)}
          hint={`${data.jobs.draft} draft · ${data.jobs.closed} closed`}
        />
        <StatCard
          label="Applicants"
          value={String(data.applications.total)}
          hint={`▲ ${data.applications.last_7_days} this week`}
          hintStyle={data.applications.last_7_days > 0 ? { color: GREEN } : undefined}
        />
        <StatCard
          label="Awaiting review"
          value={String(data.applications.new)}
          valueStyle={data.applications.new > 0 ? { color: "var(--accent)" } : undefined}
          hint="in stage: new"
        />
        <StatCard
          label="Median quiz score"
          value={medianPercent === null ? "—" : `${medianPercent}%`}
          hint={avgPercent === null ? "no completed quizzes yet" : `avg ${avgPercent}%`}
        />
        <StatCard
          label="Quiz completion"
          value={completionPercent === null ? "—" : `${completionPercent}%`}
          hint={`${data.quiz.attempts_completed} of ${data.quiz.attempts_total} attempts`}
        />
      </div>

      <ScoreDistribution quiz={data.quiz} />
      <WeeklyChart weekly={data.weekly} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="card px-5 py-[18px]">
          <div className="flex items-center justify-between">
            <h2 className="font-heading text-[15px] font-semibold">Positions</h2>
            <Link
              href="/admin/jobs"
              className="text-[13px] text-g500 hover:text-accent hover:underline"
            >
              Manage jobs
            </Link>
          </div>
          {data.per_job.length === 0 ? (
            <p className="mt-2 text-sm text-g500">
              No jobs yet —{" "}
              <Link href="/admin/jobs/new" className="text-accent underline">
                create your first
              </Link>
              .
            </p>
          ) : (
            <ul className="mt-2 divide-y divide-divider">
              {data.per_job.map((job) => (
                <li key={job.job_id} className="flex items-center justify-between gap-2 py-2.5">
                  <div className="min-w-0">
                    <Link
                      href={`/admin/jobs/${job.job_id}`}
                      className="truncate text-sm font-medium hover:text-accent hover:underline"
                    >
                      {job.title}
                    </Link>
                    <span className="ml-2 font-mono text-[11px] text-g400">{job.status}</span>
                  </div>
                  <p className="shrink-0 text-sm text-g500">
                    {job.applications} applicant{job.applications === 1 ? "" : "s"}
                    {job.new > 0 ? (
                      <span
                        className="ml-1.5 rounded-full px-1.5 py-0.5 font-mono text-[10.5px] font-semibold"
                        style={{ background: GREEN_BG, color: GREEN }}
                      >
                        {job.new} new
                      </span>
                    ) : null}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>

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
                    <span
                      className="font-mono text-[11px]"
                      style={app.stage === "new" ? { color: AMBER } : undefined}
                    >
                      {app.stage}
                    </span>
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
