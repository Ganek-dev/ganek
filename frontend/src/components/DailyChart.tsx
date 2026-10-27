import type { ReactNode } from "react";

import type { JobStats } from "@/lib/api";

/** Views and applications per day, last 30 days (spec job posts v2 5.2
 * item 3), in the dashboard's bar style: accent bars, title tooltips, no
 * animation, nothing that shifts while numbers load. Counts only. The
 * chart claims nothing about why a series is empty: the page hands it the
 * right empty state (`ViewsEmptyState`) for the job's situation. */

type Point = JobStats["daily"][number];

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** "2026-10-03" -> "Oct 3"; the day is a UTC date, so format it as one */
function shortDay(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function axisDay(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "numeric",
    day: "numeric",
    timeZone: "UTC",
  });
}

const CHART_HEIGHT = 80;

function barHeight(value: number, max: number): number {
  if (value <= 0) return 0;
  return Math.max(2, (value / max) * CHART_HEIGHT);
}

export function DailyChart({ daily, empty }: { daily: Point[]; empty?: ReactNode }) {
  const max = Math.max(1, ...daily.map((p) => Math.max(p.views, p.applications)));
  const last = daily.length - 1;
  return (
    <div className="card px-5 py-[18px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-[15px] font-semibold">
          Views and applications, last 30 days
        </h2>
        <ul className="flex items-center gap-3 font-mono text-[11px] text-g500">
          <li className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-2.5 w-2.5 rounded-[2px]"
              style={{ background: "color-mix(in oklab, var(--accent) 40%, var(--surface))" }}
            />
            views
          </li>
          <li className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-2.5 w-2.5 rounded-[2px]"
              style={{ background: "var(--accent)" }}
            />
            applications
          </li>
        </ul>
      </div>
      <div
        className="mt-3 flex h-28 items-end gap-[3px]"
        role="img"
        aria-label="Views and applications, last 30 days"
      >
        {daily.map((point, i) => (
          <div
            key={point.day}
            title={`${shortDay(point.day)}: ${plural(point.views, "view")}, ${plural(point.applications, "application")}`}
            className="flex flex-1 flex-col items-center justify-end gap-1"
          >
            <div className="relative flex w-full items-end" style={{ height: `${CHART_HEIGHT}px` }}>
              <div
                className="w-full rounded-t-[3px]"
                style={{
                  height: `${barHeight(point.views, max)}px`,
                  background: "color-mix(in oklab, var(--accent) 40%, var(--surface))",
                }}
              />
              <div
                className="absolute inset-x-0 bottom-0 rounded-t-[3px]"
                style={{
                  height: `${barHeight(point.applications, max)}px`,
                  background: "var(--accent)",
                }}
              />
            </div>
            <span className="h-3 font-mono text-[10px] text-g400">
              {(last - i) % 7 === 0 ? axisDay(point.day) : ""}
            </span>
          </div>
        ))}
      </div>
      {empty ? <div className="mt-3">{empty}</div> : null}
    </div>
  );
}
