"use client";

import { useEffect, useState } from "react";

import { applications, type TimelineEvent } from "@/lib/api";
import { relativeTime } from "@/lib/time";
import { reasonLabel } from "@/lib/rejection-reasons";

/** What happened to this application and who did it (board card
 * "Candidate timeline"): stage moves with the actor, every email with its
 * delivery state, quiz milestones, notes, interviews. Newest first. The
 * backend merges the sources; this card only puts words on the rows. */

const STAGE_LABELS: Record<string, string> = {
  new: "New",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

const EMAIL_LABELS: Record<string, string> = {
  application_received: "Application confirmation",
  quiz_invite: "Assessment invite",
  quiz_reminder: "Assessment reminder",
  stage_advance: "Advance update",
  rejection: "Rejection",
  interview_invite: "Interview booking link",
  interview_confirmed: "Interview confirmation",
  interview_scheduled: "Interviewer invite",
  interview_cancelled: "Interview cancellation",
  interview_cancelled_interviewer: "Interviewer cancel notice",
  message: "Message",
  scorecard_request: "Scorecard request",
  scorecard_reminder: "Scorecard reminder",
};

type Tone = "stage" | "quiz" | "note" | "sent" | "waiting" | "failed" | "neutral";

const DOT: Record<Tone, string> = {
  stage: "bg-accent",
  quiz: "bg-g500",
  note: "bg-blue-500",
  sent: "bg-emerald-500",
  waiting: "bg-amber-500",
  failed: "bg-red-500",
  neutral: "bg-g300",
};

const EMAIL_STATE: Record<string, { tone: Tone; label: (p: Record<string, unknown>) => string }> = {
  sent: { tone: "sent", label: () => "sent" },
  queued: {
    tone: "waiting",
    label: (p) => (Number(p.attempts) > 0 ? `retrying (attempt ${String(p.attempts)})` : "queued"),
  },
  failed: { tone: "failed", label: () => "failed" },
  bounced: { tone: "failed", label: () => "bounced" },
  complained: { tone: "failed", label: () => "marked as spam" },
  suppressed: { tone: "waiting", label: () => "skipped: address suppressed" },
};

const NOT_DELIVERED = new Set(["failed", "bounced", "complained"]);
const COLLAPSED_ROWS = 8;

function who(event: TimelineEvent, fallback = "A former teammate"): string {
  return event.actor_label || event.actor_email || fallback;
}

/** The reviewer's label as the payload carries it; a row written before the
 * label existed, or one missing the key, reads "A reviewer", never "undefined". */
function reviewerName(payload: Record<string, unknown>): string {
  return nonEmpty(payload.reviewer_label) ?? "A reviewer";
}

function stageName(value: unknown): string {
  return STAGE_LABELS[String(value)] ?? String(value);
}

function nonEmpty(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function describeEvent(event: TimelineEvent): {
  text: string;
  tone: Tone;
  /** A second line under the row: the internal rejection note, or an
   * email's subject. */
  detail?: string;
  /** The email's plain text, behind a "Show text" disclosure (PR 4). */
  body?: string;
} {
  const p = event.payload;
  switch (event.kind) {
    case "applied":
      // the source sits in the panel header; repeating it here doubled the text
      return { text: "Applied", tone: "neutral" };
    case "stage.changed": {
      if (p.to === "withdrawn" && !event.actor_label && !event.actor_email) {
        return { text: "Candidate withdrew", tone: "stage" };
      }
      const bulk = p.bulk ? " (bulk)" : "";
      const reason = p.to === "rejected" ? reasonLabel(p.reason) : null;
      const suffix = reason ? `: ${reason}` : "";
      const detail = typeof p.note === "string" && p.note.trim() ? p.note : undefined;
      return { text: `${who(event)} moved to ${stageName(p.to)}${suffix}${bulk}`, tone: "stage", detail };
    }
    case "quiz.invited":
      return { text: "Assessment link issued", tone: "quiz" };
    case "quiz.started":
      return { text: "Quiz started", tone: "quiz" };
    case "quiz.completed": {
      const score = typeof p.score === "number" ? ` - ${Math.round(p.score * 100)}%` : "";
      return { text: `Quiz completed${score}`, tone: "quiz" };
    }
    case "quiz.expired":
      return { text: "Assessment link expired", tone: "quiz" };
    case "quiz.reissued": {
      const reason = p.reason ? ` (${String(p.reason)})` : "";
      return { text: `${who(event, "System")} re-issued the assessment${reason}`, tone: "quiz" };
    }
    case "quiz.extra_time":
      return Number(p.time_multiplier) > 1
        ? { text: `${who(event)} granted ${String(p.time_multiplier)}x quiz time`, tone: "quiz" }
        : { text: `${who(event)} removed the extra-time grant`, tone: "quiz" };
    case "email": {
      const state = EMAIL_STATE[String(p.status)] ?? EMAIL_STATE.queued;
      const name = EMAIL_LABELS[String(p.template)] ?? String(p.template);
      // subject and text are set once the row was rendered at delivery
      return {
        text: `${name} email ${state.label(p)}`,
        tone: state.tone,
        detail: nonEmpty(p.subject),
        body: nonEmpty(p.text),
      };
    }
    case "scorecard.requested":
      return { text: `Scorecard requested from ${reviewerName(p)}`, tone: "neutral" };
    case "scorecard.submitted":
      return { text: `Scorecard submitted by ${reviewerName(p)}`, tone: "sent" };
    case "scorecard.declined":
      return { text: `Scorecard declined by ${reviewerName(p)}`, tone: "neutral" };
    case "scorecard.dismissed":
      return { text: "Scorecard request withdrawn", tone: "neutral" };
    case "email.message":
      return { text: `${who(event)} sent a message`, tone: "sent" };
    case "note.added":
      return { text: `${who(event)} added a note`, tone: "note" };
    case "interview.requested":
      return { text: `${who(event)} sent an interview invite`, tone: "stage" };
    case "interview.booked":
      return { text: "Candidate booked the interview", tone: "stage" };
    case "interview.cancelled":
      return { text: `${who(event, "Candidate")} cancelled the interview`, tone: "stage" };
    case "candidate.email_updated":
      return { text: `${who(event)} corrected the email address`, tone: "neutral" };
    default:
      return { text: event.kind, tone: "neutral" };
  }
}

function failureHint(events: TimelineEvent[]): string | null {
  const emails = events.filter((event) => event.kind === "email");
  const failed = emails.filter((event) => NOT_DELIVERED.has(String(event.payload.status)));
  if (failed.length === 0) return null;
  if (failed.some((event) => event.payload.status !== "failed")) {
    return "The provider reported a bounce or a spam complaint - that address is now skipped. Reach the candidate another way.";
  }
  if (failed.some((event) => event.payload.last_error === "Email not configured")) {
    return "Email is not configured on this instance - nothing is being delivered.";
  }
  return "Delivery failed after retries - check your email settings and use the test send on the Privacy page under Settings.";
}

export function TimelineCard({
  applicationId,
  now,
  refreshKey = 0,
}: {
  applicationId: string;
  now: Date;
  /** Bump after an action in the panel (stage move, reminder) so the trail
   * refetches without flashing back to the skeleton. */
  refreshKey?: number;
}) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    applications
      .timeline(applicationId)
      .then((list) => {
        if (!cancelled) setEvents(list);
      })
      .catch(() => {
        if (!cancelled) setFailed(true); // decoration: never breaks the panel
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId, refreshKey]);

  const hint = events ? failureHint(events) : null;
  const visible = events && !expanded ? events.slice(0, COLLAPSED_ROWS) : events;
  const hidden = events && visible ? events.length - visible.length : 0;

  return (
    <section aria-label="Timeline" className="card mt-5 p-4">
      <p className="text-[13px] font-semibold">Timeline</p>
      {failed ? (
        <p className="mt-2 text-[12.5px] text-g500">The timeline could not be loaded.</p>
      ) : visible === null ? (
        <div aria-busy="true" className="mt-2.5 space-y-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-4 animate-pulse rounded-sm bg-muted-fill" />
          ))}
        </div>
      ) : (
        <>
          <ol className="mt-2.5 space-y-1.5">
            {visible.map((event) => {
              const { text, tone, detail, body } = describeEvent(event);
              return (
                <li key={event.id} className="text-[13px]">
                  <div className="flex items-baseline gap-2">
                    <span
                      aria-hidden
                      className={`inline-block h-1.5 w-1.5 shrink-0 self-center rounded-full ${DOT[tone]}`}
                    />
                    <span className="text-g700">{text}</span>
                    <time
                      dateTime={event.at}
                      title={new Date(event.at).toLocaleString()}
                      className="ml-auto shrink-0 font-mono text-[11px] text-g500"
                    >
                      {relativeTime(event.at, now)}
                    </time>
                  </div>
                  {detail ? (
                    <p className="ml-3.5 whitespace-pre-wrap text-[12px] text-g500">{detail}</p>
                  ) : null}
                  {body ? (
                    <details className="ml-3.5">
                      <summary className="cursor-pointer text-[12px] text-g600 underline hover:text-accent">
                        Show text
                      </summary>
                      <pre className="mt-1 rounded-md border border-edge bg-muted-fill p-2 font-mono text-[11.5px] leading-[17px] whitespace-pre-wrap text-g700">
                        {body}
                      </pre>
                    </details>
                  ) : null}
                </li>
              );
            })}
          </ol>
          {hidden > 0 ? (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="mt-2 text-[12px] text-g600 underline hover:text-accent"
            >
              Show {hidden} more
            </button>
          ) : null}
          {hint ? (
            <p className="mt-2 text-[11.5px] text-red-600 dark:text-red-400">{hint}</p>
          ) : null}
        </>
      )}
    </section>
  );
}
