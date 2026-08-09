"use client";

import { useCallback, useEffect, useState } from "react";

import { CalendarPlus, Video } from "lucide-react";

import { interviews, team, type InterviewAdmin, type TeamUser } from "@/lib/api";

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

/** Interview scheduling card for the applicant detail panel (screen 11 → 23).

Self-contained: fetches its own state per application so the (large)
applicants page stays lean. States: none → schedule dialog → pending →
booked → (cancel) → back to none. */

const DURATIONS = [15, 30, 45, 60] as const;

function fmt(iso: string, timezone: string): string {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: timezone,
  });
  const time = d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: timezone,
  });
  return `${day} · ${time}`;
}

function ScheduleDialogBody({
  applicationId,
  onCreated,
}: {
  applicationId: string;
  onCreated: (interview: InterviewAdmin) => void;
}) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [members, setMembers] = useState<TeamUser[]>([]);
  const [interviewer, setInterviewer] = useState("");
  const [duration, setDuration] = useState<number>(45);
  const [description, setDescription] = useState("");
  const [teamError, setTeamError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Preview result keyed by the (interviewer, duration) it answers, so a
  // change in selection is "loading" for free — no synchronous setState at
  // the top of the effect body is needed (lint rule
  // `react-hooks/set-state-in-effect`; see JobForm.tsx for the same pattern).
  const [previewResult, setPreviewResult] = useState<{
    key: string;
    preview?: { schedule_summary: string; open_slot_count: number };
    error?: string;
  } | null>(null);

  useEffect(() => {
    team
      .list()
      .then((users) => {
        const active = users.filter((u) => u.is_active);
        setMembers(active);
        setInterviewer((current) => current || (active[0]?.id ?? ""));
      })
      .catch(() => setTeamError("Couldn't load the team list"));
  }, []);

  const previewKey = interviewer ? `${interviewer}:${duration}:${timezone}` : null;

  useEffect(() => {
    if (!interviewer) return;
    let cancelled = false;
    const key = `${interviewer}:${duration}:${timezone}`;
    interviews
      .preview(applicationId, { interviewer_user_id: interviewer, duration_minutes: duration, timezone })
      .then((result) => {
        if (cancelled) return;
        setPreviewResult({ key, preview: result });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPreviewResult({
          key,
          error:
            err instanceof Error && /calendar/i.test(err.message)
              ? "Interviewer needs to connect Google Calendar in Settings → Account first."
              : err instanceof Error
                ? err.message
                : "Failed to load availability",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId, interviewer, duration, timezone]);

  const isPreviewCurrent = previewResult !== null && previewResult.key === previewKey;
  const preview = isPreviewCurrent ? (previewResult?.preview ?? null) : null;
  const previewError = isPreviewCurrent ? (previewResult?.error ?? null) : null;
  const previewLoading = previewKey !== null && !isPreviewCurrent;

  async function send() {
    setSendError(null);
    setBusy(true);
    try {
      const created = await interviews.create(applicationId, {
        interviewer_user_id: interviewer,
        duration_minutes: duration,
        timezone,
        description,
      });
      onCreated(created);
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Failed to send the invite");
      setBusy(false);
    }
  }

  const interviewerEmail = members.find((m) => m.id === interviewer)?.email ?? "";
  const noOpenTimes = preview !== null && preview.open_slot_count === 0;
  const error = teamError ?? previewError ?? sendError;

  return (
    <div className="mt-3 space-y-3">
      <label className="flex flex-col gap-1.5">
        <span className="text-[12.5px] font-medium">Interviewer</span>
        <select
          value={interviewer}
          onChange={(event) => setInterviewer(event.target.value)}
          className="h-9 rounded-md border border-edge bg-surface px-2.5 text-[13px] outline-none focus:border-accent"
        >
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.email}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] font-medium">Duration</span>
        <div className="flex overflow-hidden rounded-md border border-edge" role="group">
          {DURATIONS.map((minutes) => (
            <button
              key={minutes}
              type="button"
              aria-pressed={duration === minutes}
              onClick={() => setDuration(minutes)}
              className={`h-8 px-3 font-mono text-[12px] ${
                duration === minutes
                  ? "bg-inverse text-inverse-foreground"
                  : "bg-surface hover:bg-muted-fill/60"
              }`}
            >
              {minutes}m
            </button>
          ))}
        </div>
        <span className="rounded-full border border-edge px-2 py-0.5 font-mono text-[10.5px] text-g500">
          {timezone}
        </span>
      </div>
      <label className="flex flex-col gap-1.5">
        <span className="text-[12.5px] font-medium">What to expect (shown to the candidate)</span>
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Your work, our stack, and what the first 90 days look like."
          className="rounded-md border border-edge bg-surface px-2.5 py-2 text-[13px] outline-none focus:border-accent"
        />
      </label>

      {previewLoading ? (
        <div className="h-4 w-2/3 animate-pulse rounded bg-muted-fill" />
      ) : preview !== null ? (
        <p className="text-[12.5px] text-g500">
          Uses {interviewerEmail.split("@")[0]}&apos;s availability ({preview.schedule_summary}) —{" "}
          {preview.open_slot_count} open times in the next 2 weeks
        </p>
      ) : null}

      {noOpenTimes ? (
        <p className="text-[12.5px] text-amber-600 dark:text-amber-400">
          No open times in the next 2 weeks — ask them to clear some calendar space or widen
          their availability.
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={busy || preview === null || preview.open_slot_count === 0}
          onClick={send}
          className="inline-flex h-8 items-center rounded-md bg-inverse px-3.5 text-[13px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : "Send invite"}
        </button>
        <DialogClose asChild>
          <button type="button" className="text-[12.5px] text-g500 hover:underline">
            Cancel
          </button>
        </DialogClose>
      </div>
    </div>
  );
}

export function InterviewCard({ applicationId }: { applicationId: string }) {
  const [interview, setInterview] = useState<InterviewAdmin | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // State resets between applicants via the key on the usage site — the
  // effect itself must stay side-effect-only (react-hooks lint).
  const load = useCallback(() => {
    interviews
      .get(applicationId)
      .then((current) => {
        setInterview(current);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [applicationId]);

  useEffect(load, [load]);

  async function cancel() {
    setError(null);
    try {
      await interviews.cancel(applicationId);
      setInterview(null);
      setConfirmingCancel(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel");
    }
  }

  if (!loaded) {
    return <div aria-busy="true" className="h-16 animate-pulse rounded-md bg-muted-fill" />;
  }

  return (
    <section className="rounded-md border border-edge p-3.5">
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-1.5 text-[13px] font-semibold">
          <CalendarPlus aria-hidden className="h-4 w-4 text-g500" />
          Interview
        </p>
        {interview === null ? (
          <Dialog open={scheduling} onOpenChange={setScheduling}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="inline-flex h-7 items-center rounded-md bg-inverse px-3 text-[12.5px] font-medium text-inverse-foreground hover:brightness-[0.94]"
              >
                Schedule interview
              </button>
            </DialogTrigger>
            <DialogContent>
              <DialogTitle>Schedule interview</DialogTitle>
              <ScheduleDialogBody
                applicationId={applicationId}
                onCreated={(created) => {
                  setInterview(created);
                  setScheduling(false);
                }}
              />
            </DialogContent>
          </Dialog>
        ) : null}
      </div>

      {interview !== null ? (
        <div className="mt-2 space-y-1.5">
          {interview.status === "pending" ? (
            <p className="text-[12.5px] text-g500">
              Awaiting candidate · uses {interview.interviewer_email}&apos;s availability
            </p>
          ) : (
            <p className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <span className="font-mono">
                {interview.scheduled_start
                  ? fmt(interview.scheduled_start, interview.timezone)
                  : "—"}
              </span>
              <span className="text-g500">
                {interview.duration_minutes}m · {interview.interviewer_email}
              </span>
              {interview.meet_url ? (
                <a
                  href={interview.meet_url}
                  className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                >
                  <Video aria-hidden className="h-3.5 w-3.5" />
                  Meet
                </a>
              ) : null}
            </p>
          )}
          {confirmingCancel ? (
            <p className="flex items-center gap-2 text-[12.5px]">
              Cancel this interview?
              <button
                type="button"
                onClick={cancel}
                className="font-semibold text-red-600 hover:underline dark:text-red-400"
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
            </p>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingCancel(true)}
              className="text-[12px] text-g500 hover:text-red-600 hover:underline dark:hover:text-red-400"
            >
              Cancel interview
            </button>
          )}
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </section>
  );
}
