"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CalendarX2, Check, Clock, Video } from "lucide-react";

import { ApiError, publicInterviews, type InterviewPublic } from "@/lib/api";
import { brandStyle } from "@/lib/brand";

/** Candidate interview scheduling, handoff screen 23: interviewer panel +
 * day-grouped slot grid (mono time pills, selected = brand fill) + confirm
 * bar. Booked state offers reschedule (same grid) and a two-step cancel.
 * All times render in the INTERVIEW's timezone — the calendar invite that
 * Google sends after booking converts to the candidate's own calendar. */

const DAYS_PER_PAGE = 4;

function initials(display: string): string {
  const parts = display.split(/\s+/).filter(Boolean);
  const source = parts.length >= 2 ? parts[0][0] + parts[1][0] : display.slice(0, 2);
  return source.toUpperCase();
}

function tzShortName(timezone: string, iso?: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      timeZoneName: "short",
    }).formatToParts(iso ? new Date(iso) : new Date());
    return parts.find((p) => p.type === "timeZoneName")?.value ?? "";
  } catch {
    return "";
  }
}

function dayLabel(iso: string, timezone: string): { weekday: string; date: string } {
  const d = new Date(iso);
  return {
    weekday: d.toLocaleDateString("en-US", { weekday: "short", timeZone: timezone }),
    date: d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: timezone }),
  };
}

function timeLabel(iso: string, timezone: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: timezone,
  });
}

function dayKey(iso: string, timezone: string): string {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: timezone });
}

function endTime(iso: string, minutes: number, timezone: string): string {
  return timeLabel(new Date(new Date(iso).getTime() + minutes * 60_000).toISOString(), timezone);
}

function SlotGrid({
  interview,
  selected,
  onSelect,
}: {
  interview: InterviewPublic;
  selected: string | null;
  onSelect: (iso: string) => void;
}) {
  const [page, setPage] = useState(0);
  const days = useMemo(() => {
    const grouped = new Map<string, string[]>();
    for (const iso of interview.available_slots) {
      const key = dayKey(iso, interview.timezone);
      grouped.set(key, [...(grouped.get(key) ?? []), iso]);
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [interview]);

  const pages = Math.max(1, Math.ceil(days.length / DAYS_PER_PAGE));
  const visible = days.slice(page * DAYS_PER_PAGE, page * DAYS_PER_PAGE + DAYS_PER_PAGE);

  if (days.length === 0) {
    return (
      <p className="rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5 text-[13px] text-g500">
        No open times right now — the hiring team has been notified to offer new slots.
      </p>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {visible.map(([key, slots]) => {
          const label = dayLabel(slots[0], interview.timezone);
          return (
            <div key={key} className="flex flex-col gap-2">
              <p className="text-center text-[12.5px] font-medium">
                {label.weekday}{" "}
                <span className="font-mono text-[11.5px] text-g500">{label.date}</span>
              </p>
              {slots.map((iso) => (
                <button
                  key={iso}
                  type="button"
                  onClick={() => onSelect(iso)}
                  aria-pressed={selected === iso}
                  className={`h-9 rounded-md border font-mono text-[12.5px] transition-colors ${
                    selected === iso
                      ? "border-brand bg-brand text-brand-foreground"
                      : "border-edge bg-surface hover:border-strong"
                  }`}
                >
                  {timeLabel(iso, interview.timezone)}
                </button>
              ))}
            </div>
          );
        })}
      </div>
      {pages > 1 ? (
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            className="text-[12.5px] font-medium text-g500 hover:text-g600 disabled:opacity-40"
          >
            ← back
          </button>
          <button
            type="button"
            disabled={page >= pages - 1}
            onClick={() => setPage((p) => p + 1)}
            className="text-[12.5px] font-medium text-accent hover:underline disabled:opacity-40"
          >
            more days →
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default function InterviewBookingPage() {
  const { token } = useParams<{ token: string }>();
  const [interview, setInterview] = useState<InterviewPublic | null>(null);
  const [invalid, setInvalid] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rescheduling, setRescheduling] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);

  const load = useCallback(() => {
    publicInterviews
      .get(token)
      .then(setInterview)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setInvalid(true);
        else setError(err instanceof Error ? err.message : "Failed to load");
      });
  }, [token]);

  useEffect(load, [load]);

  async function submit(action: "book" | "reschedule") {
    if (!selected) return;
    setError(null);
    setBusy(true);
    try {
      const updated =
        action === "book"
          ? await publicInterviews.book(token, selected)
          : await publicInterviews.reschedule(token, selected);
      setInterview(updated);
      setSelected(null);
      setRescheduling(false);
    } catch (err) {
      if (err instanceof ApiError && err.detail === "slot-taken") {
        setError("That time was just taken — please pick another.");
        setSelected(null);
        load();
      } else if (err instanceof ApiError && err.status === 503) {
        setError("Scheduling is temporarily unavailable — please try again in a bit.");
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong");
      }
    } finally {
      setBusy(false);
    }
  }

  async function cancelInterview() {
    setError(null);
    setBusy(true);
    try {
      setInterview(await publicInterviews.cancel(token));
      setConfirmingCancel(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (invalid) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface text-foreground px-4">
        <div className="card max-w-[420px] p-6 text-center">
          <CalendarX2 aria-hidden className="mx-auto h-8 w-8 text-g400" />
          <h1 className="mt-3 font-heading text-lg font-semibold">
            This scheduling link isn&apos;t valid anymore
          </h1>
          <p className="mt-2 text-[13px] text-g500">
            It may have been replaced. Check your inbox for a newer invitation, or reply to
            the hiring team&apos;s email.
          </p>
        </div>
      </main>
    );
  }

  if (interview === null) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface text-foreground px-4">
        <div aria-busy="true" className="w-full max-w-[720px] space-y-3">
          <div className="h-28 animate-pulse rounded-lg bg-muted-fill" />
          <div className="h-64 animate-pulse rounded-lg bg-muted-fill" />
        </div>
      </main>
    );
  }

  const tz = `${interview.timezone} · ${tzShortName(interview.timezone)}`;
  const showGrid = interview.status === "pending" || (interview.status === "booked" && rescheduling);

  return (
    <main
      style={brandStyle(interview.brand_primary)}
      className="flex min-h-screen justify-center bg-surface text-foreground px-4 py-10"
    >
      <div className="w-full max-w-[760px]">
        <p className="text-center text-[13px] font-semibold">{interview.company_name}</p>

        {interview.status === "cancelled" ? (
          <div className="card mt-6 p-6 text-center">
            <CalendarX2 aria-hidden className="mx-auto h-8 w-8 text-g400" />
            <h1 className="mt-3 font-heading text-lg font-semibold">
              This interview was cancelled
            </h1>
            <p className="mt-2 text-[13px] text-g500">
              If a new time is needed, {interview.company_name} will send you a fresh link.
            </p>
          </div>
        ) : (
          <>
            <h1 className="mt-6 text-center font-heading text-[26px] font-semibold tracking-[-0.01em]">
              {interview.status === "booked" && !rescheduling
                ? "You're booked in"
                : `Pick a time, ${interview.candidate_first_name}`}
            </h1>
            <p className="mt-1 text-center text-[13.5px] text-g500">
              {interview.title} · {interview.job_title}
            </p>

            <div className="card mt-6 flex flex-wrap items-center gap-4 p-4">
              <div
                aria-hidden
                className="flex h-11 w-11 items-center justify-center rounded-full text-sm font-bold text-brand"
                style={{
                  background: "color-mix(in oklab, var(--brand-primary) 12%, var(--surface))",
                }}
              >
                {initials(interview.interviewer_display)}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{interview.interviewer_display}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-g500">
                  <span className="inline-flex items-center gap-1">
                    <Clock aria-hidden className="h-3.5 w-3.5" />
                    {interview.duration_minutes} minutes
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Video aria-hidden className="h-3.5 w-3.5" />
                    Google Meet — invite lands in your inbox
                  </span>
                </p>
              </div>
              <span className="rounded-full border border-edge px-2.5 py-1 font-mono text-[11px] text-g500">
                {tz}
              </span>
              {interview.description ? (
                <p className="w-full border-t border-edge pt-3 text-[13px] text-g600 italic">
                  {interview.description}
                </p>
              ) : null}
            </div>

            {interview.status === "booked" && !rescheduling ? (
              <div className="card mt-4 p-5">
                <p className="flex items-center gap-2 text-sm font-semibold">
                  <Check aria-hidden className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                  {interview.scheduled_start
                    ? `${dayLabel(interview.scheduled_start, interview.timezone).weekday}, ${
                        dayLabel(interview.scheduled_start, interview.timezone).date
                      } · ${timeLabel(interview.scheduled_start, interview.timezone)}–${endTime(
                        interview.scheduled_start,
                        interview.duration_minutes,
                        interview.timezone,
                      )}`
                    : "Booked"}
                </p>
                <p className="mt-1 text-[12.5px] text-g500">{tz} · Google Meet</p>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  {interview.meet_url ? (
                    <a
                      href={interview.meet_url}
                      className="inline-flex h-9 items-center rounded-md bg-brand px-4 text-[13.5px] font-semibold text-brand-foreground hover:brightness-[0.94]"
                    >
                      Open Meet link
                    </a>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setRescheduling(true)}
                    className="inline-flex h-9 items-center rounded-md border border-edge px-4 text-[13.5px] font-medium hover:bg-muted-fill/50"
                  >
                    Reschedule
                  </button>
                  {confirmingCancel ? (
                    <span className="inline-flex items-center gap-2 text-[13px]">
                      Cancel this interview?
                      <button
                        type="button"
                        disabled={busy}
                        onClick={cancelInterview}
                        className="font-semibold text-red-600 hover:underline disabled:opacity-50 dark:text-red-400"
                      >
                        Yes, cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingCancel(false)}
                        className="text-g500 hover:underline"
                      >
                        Keep it
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmingCancel(true)}
                      className="text-[13px] text-g500 hover:text-red-600 hover:underline dark:hover:text-red-400"
                    >
                      Cancel interview
                    </button>
                  )}
                </div>
              </div>
            ) : null}

            {showGrid ? (
              <div className="card mt-4 p-5">
                {rescheduling ? (
                  <p className="mb-4 text-[13px] text-g500">
                    Pick a new time — your current slot stays until you confirm.
                  </p>
                ) : null}
                <SlotGrid interview={interview} selected={selected} onSelect={setSelected} />
                {selected ? (
                  <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-edge pt-4">
                    <p className="text-[13.5px]">
                      <span className="font-semibold">
                        {dayLabel(selected, interview.timezone).weekday},{" "}
                        {dayLabel(selected, interview.timezone).date} ·{" "}
                        {timeLabel(selected, interview.timezone)}–
                        {endTime(selected, interview.duration_minutes, interview.timezone)}
                      </span>{" "}
                      <span className="font-mono text-[11.5px] text-g500">
                        {tzShortName(interview.timezone, selected)} · Google Meet
                      </span>
                    </p>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => submit(rescheduling ? "reschedule" : "book")}
                      className="inline-flex h-10 items-center rounded-md bg-brand px-5 text-[14px] font-semibold text-brand-foreground hover:brightness-[0.94] disabled:opacity-50"
                    >
                      {busy ? "…" : rescheduling ? "Confirm new time" : "Confirm interview"}
                    </button>
                  </div>
                ) : null}
                {rescheduling ? (
                  <button
                    type="button"
                    onClick={() => {
                      setRescheduling(false);
                      setSelected(null);
                    }}
                    className="mt-3 text-[12.5px] text-g500 hover:underline"
                  >
                    Never mind, keep the current time
                  </button>
                ) : null}
              </div>
            ) : null}

            {error ? (
              <p role="alert" className="mt-4 text-center text-sm text-red-600 dark:text-red-400">
                {error}
              </p>
            ) : null}

            <p className="mt-6 text-center font-mono text-[10.5px] text-g400">
              Reschedule or cancel any time from this page or the invite email.
            </p>
          </>
        )}
      </div>
    </main>
  );
}
