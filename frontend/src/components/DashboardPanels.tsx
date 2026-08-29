"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Activity, CalendarDays, ListTodo, Plus, Video } from "lucide-react";

import {
  dashboard,
  type ActivityItem,
  type StatsOverview,
  type TaskItem,
  type TodayPanelData,
} from "@/lib/api";
import { relativeTime } from "@/lib/time";

/** Dashboard 06 right-rail trio: Today (calendar), Your queue (derived +
 * manual tasks), Activity feed. Each panel fetches its own data. */

function timeOf(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—"; // all-day events come as bare dates
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}


const panelCls = "card flex min-h-[180px] flex-col p-4";
const headCls =
  "flex items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] text-g500 uppercase";

export function TodayPanel() {
  const [data, setData] = useState<TodayPanelData | null>(null);

  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    dashboard
      .today(tz)
      .then(setData)
      .catch(() => setData({ source: "ganek", events: [] }));
  }, []);

  return (
    <section className={panelCls}>
      <h2 className={headCls}>
        <CalendarDays aria-hidden className="h-3.5 w-3.5" />
        Today
        {data?.source === "google" ? (
          <span className="ml-auto normal-case tracking-normal text-g400">Google Calendar</span>
        ) : null}
      </h2>
      {data === null ? (
        <div aria-busy="true" className="mt-3 h-20 animate-pulse rounded-md bg-muted-fill" />
      ) : data.events.length === 0 ? (
        <p className="mt-3 text-[12.5px] text-g500">
          Nothing scheduled today.
          {data.source === "ganek" ? (
            <>
              {" "}
              <Link href="/admin/account" className="text-accent hover:underline">
                Connect Google Calendar
              </Link>{" "}
              to see your whole day here.
            </>
          ) : null}
        </p>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {data.events.map((event, index) => (
            <li key={index} className="flex items-start gap-2.5">
              <span className="mt-0.5 w-11 shrink-0 font-mono text-[11.5px] text-g500">
                {timeOf(event.start)}
              </span>
              <div className="min-w-0">
                <p className="truncate text-[13px] font-medium">{event.summary}</p>
                {event.hangout_link ? (
                  <a
                    href={event.hangout_link}
                    className="inline-flex items-center gap-1 text-[11.5px] text-accent hover:underline"
                  >
                    <Video aria-hidden className="h-3 w-3" />
                    Meet
                  </a>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function QueuePanel({ overview }: { overview: StatsOverview | null }) {
  const [tasks, setTasks] = useState<TaskItem[] | null>(null);
  const [title, setTitle] = useState("");

  const load = useCallback(() => {
    dashboard.tasks
      .list()
      .then(setTasks)
      .catch(() => setTasks([]));
  }, []);

  useEffect(load, [load]);

  async function add(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    setTitle("");
    try {
      const created = await dashboard.tasks.create(trimmed);
      setTasks((current) => [...(current ?? []), created]);
    } catch {
      load();
    }
  }

  async function complete(task: TaskItem) {
    setTasks((current) => (current ?? []).filter((t) => t.id !== task.id));
    try {
      await dashboard.tasks.toggle(task.id, true);
    } catch {
      load();
    }
  }

  const derived = (overview?.per_job ?? [])
    .filter((job) => job.new > 0)
    .map((job) => ({
      key: `new-${job.job_id}`,
      title: `Review ${job.new} new applicant${job.new === 1 ? "" : "s"}`,
      hint: job.title,
      href: "/admin/applicants",
    }));
  const openCount = derived.length + (tasks?.length ?? 0);

  return (
    <section className={panelCls}>
      <h2 className={headCls}>
        <ListTodo aria-hidden className="h-3.5 w-3.5" />
        Your queue
        <span className="ml-auto normal-case tracking-normal text-g400">{openCount} open</span>
      </h2>
      <ul className="mt-3 space-y-2">
        {derived.map((item) => (
          <li key={item.key}>
            <Link href={item.href} className="group block">
              <p className="text-[13px] font-medium group-hover:underline">{item.title}</p>
              <p className="text-[11.5px] text-g500">{item.hint}</p>
            </Link>
          </li>
        ))}
        {(tasks ?? []).map((task) => (
          <li key={task.id} className="flex items-start gap-2">
            <input
              type="checkbox"
              aria-label={`Done: ${task.title}`}
              checked={false}
              onChange={() => complete(task)}
              className="mt-0.5"
            />
            <div className="min-w-0">
              <p className="text-[13px] font-medium">{task.title}</p>
              {task.note ? <p className="text-[11.5px] text-g500">{task.note}</p> : null}
            </div>
          </li>
        ))}
        {tasks !== null && openCount === 0 ? (
          <li className="text-[12.5px] text-g500">All clear — nothing waiting on you.</li>
        ) : null}
      </ul>
      <form onSubmit={add} className="mt-auto flex items-center gap-1.5 pt-3">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Add a task…"
          aria-label="Add a task"
          maxLength={200}
          className="h-8 w-full rounded-md border border-edge bg-surface px-2.5 text-[12.5px] outline-none focus:border-accent"
        />
        <button
          type="submit"
          aria-label="Add task"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-edge hover:bg-muted-fill/50"
        >
          <Plus aria-hidden className="h-4 w-4" />
        </button>
      </form>
    </section>
  );
}

function activityCopy(item: ActivityItem): string {
  const p = item.payload;
  switch (item.type) {
    case "application.received":
      return `${String(p.candidate ?? "Someone")} applied — ${String(p.job ?? "a job")}`;
    case "stage.changed":
      return `${item.actor_email ?? "Someone"} moved a candidate ${String(p.from)} → ${String(p.to)}`;
    case "quiz.finished": {
      const score = typeof p.score === "number" ? ` — ${Math.round(p.score * 100)}%` : "";
      return `Assessment completed${score}`;
    }
    case "quiz.reissued":
      return `${item.actor_email ?? "Someone"} re-issued an assessment`;
    case "interview.requested":
      return `Interview invite sent (${String(p.interviewer ?? "")})`.replace(" ()", "");
    case "interview.booked":
      return "Interview booked by the candidate";
    case "interview.cancelled":
      return "Interview cancelled";
    case "candidate.erased":
      return `Candidate data erased (${Number(p.applications) || 0} application(s))`;
    case "candidate.email_updated":
      return `${item.actor_email ?? "Someone"} corrected a candidate's email`;
    case "candidate.data_requested":
      return "A candidate asked for a copy of their data";
    case "candidate.deletion_requested":
      return "A candidate asked for their data to be deleted";
    case "user.anonymized":
      return `${item.actor_email ?? "Someone"} removed a teammate's account`;
    case "retention.purged":
      return `Retention purge removed ${Number(p.applications) || 0} application(s)`;
    default:
      return item.type;
  }
}

export function ActivityPanel() {
  const [items, setItems] = useState<ActivityItem[] | null>(null);

  useEffect(() => {
    dashboard
      .activity()
      .then(setItems)
      .catch(() => setItems([]));
  }, []);

  return (
    <section className={panelCls}>
      <h2 className={headCls}>
        <Activity aria-hidden className="h-3.5 w-3.5" />
        Activity
      </h2>
      {items === null ? (
        <div aria-busy="true" className="mt-3 h-20 animate-pulse rounded-md bg-muted-fill" />
      ) : items.length === 0 ? (
        <p className="mt-3 text-[12.5px] text-g500">Activity shows up as candidates apply.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li key={item.id} className="flex items-baseline justify-between gap-2">
              <p className="min-w-0 truncate text-[12.5px]">{activityCopy(item)}</p>
              <span className="shrink-0 font-mono text-[10.5px] text-g400">
                {relativeTime(item.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
