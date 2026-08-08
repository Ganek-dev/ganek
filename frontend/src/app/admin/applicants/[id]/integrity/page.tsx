"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ArrowLeft, Check, RotateCcw } from "lucide-react";

import {
  api,
  applications,
  type ApplicationOut,
  type QuizAnswerReview,
  type QuizResult,
} from "@/lib/api";

/** Integrity review, handoff screen 24: telemetry stat cards, session
 * timeline, per-question event log, flag callouts, and the three decisions
 * — dismiss, invalidate & re-invite, reject. Flags inform humans; nothing
 * here auto-rejects. */

function formatMinSec(ms: number): string {
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function formatTaken(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return `${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}

const EVENT_LABELS: Record<string, string> = {
  blur: "window blur",
  paste: "paste",
  resize: "viewport resized",
};

export default function IntegrityReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [app, setApp] = useState<ApplicationOut | null>(null);
  const [jobTitle, setJobTitle] = useState<string>("");
  const [answers, setAnswers] = useState<QuizAnswerReview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<"reissue" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    applications
      .get(id)
      .then((data) => {
        setApp(data);
        api.jobs
          .get(data.job_id)
          .then((job) => setJobTitle(job.title))
          .catch(() => setJobTitle(""));
        if (data.quiz_attempt?.status === "completed") {
          applications
            .quizAnswers(id)
            .then(setAnswers)
            .catch(() => setAnswers([]));
        } else {
          setAnswers([]);
        }
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load applicant"),
      );
  }, [id]);
  useEffect(reload, [reload]);

  async function act(action: () => Promise<unknown>, done: string) {
    setError(null);
    setNotice(null);
    setBusy(true);
    setConfirming(null);
    try {
      await action();
      setNotice(done);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (app === null) {
    return (
      <section aria-busy="true" className="space-y-3">
        <div className="h-7 w-64 animate-pulse rounded-sm bg-muted-fill" />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-[84px] animate-pulse rounded-lg bg-muted-fill" />
          ))}
        </div>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
      </section>
    );
  }

  const attempt: QuizResult | null = app.quiz_attempt;
  const integrity = attempt?.integrity ?? {};
  const flags = integrity.flags ?? [];
  const reviewed = integrity.review !== undefined;
  const needsReview = flags.length > 0 && !reviewed;
  const scorePercent =
    attempt?.score === null || attempt?.score === undefined
      ? null
      : Math.round(attempt.score * 100);
  const taken = formatTaken(attempt?.completed_at ?? null);
  const blurredQuestions = new Set(
    (answers ?? [])
      .filter((answer) => answer.integrity_events.some((event) => event.type === "blur"))
      .map((answer) => answer.question_id),
  );

  return (
    <section className="max-w-[880px] space-y-4">
      <div>
        <Link
          href="/admin/applicants"
          className="inline-flex items-center gap-1 text-[12.5px] text-g500 hover:text-g700"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          Applicants
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2.5">
          <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">
            {app.candidate.name}
          </h1>
          <span className="font-heading text-[22px] font-light text-g300">/</span>
          <span className="font-heading text-[22px] font-semibold tracking-[-0.01em] text-g500">
            Integrity review
          </span>
          {needsReview ? (
            <span className="inline-flex h-6 items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 text-[11.5px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              needs review
            </span>
          ) : null}
          {reviewed ? (
            <span className="inline-flex h-6 items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 text-[11.5px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
              <Check aria-hidden className="h-3 w-3" />
              flags dismissed
            </span>
          ) : null}
          {integrity.reissue ? (
            <span className="inline-flex h-6 items-center gap-1 rounded-full border border-edge bg-muted-fill px-2.5 text-[11.5px] font-medium text-g600">
              <RotateCcw aria-hidden className="h-3 w-3" />
              re-issued ({integrity.reissue.reason === "expired" ? "link expired" : "integrity"}
              {integrity.reissue.mode === "auto" ? ", auto" : ""})
            </span>
          ) : null}
          {integrity.reissue_requested ? (
            <span className="inline-flex h-6 items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 text-[11.5px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              candidate requested a new link
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-[13px] text-g500">
          {jobTitle ? `${jobTitle} quiz` : "Assessment"}
          {scorePercent !== null ? (
            <>
              {" "}
              · scored <b className="font-semibold text-g700">{scorePercent}</b>
            </>
          ) : (
            <> · {attempt?.status ?? "no attempt"}</>
          )}
          {taken ? ` · taken ${taken}` : ""}
        </p>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          {notice}
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Window blurs", value: String(integrity.blur_count ?? 0) },
          { label: "Resizes", value: String(integrity.resize_count ?? 0) },
          { label: "Paste events", value: String(integrity.paste_count ?? 0) },
          { label: "Time off-screen", value: formatMinSec(integrity.blur_total_ms ?? 0) },
        ].map((stat) => (
          <div key={stat.label} className="card px-4 py-3.5">
            <p className="text-xs text-g500">{stat.label}</p>
            <p className="mt-1.5 font-heading text-[24px] leading-none font-semibold">
              {stat.value}
            </p>
          </div>
        ))}
      </div>

      {answers !== null && answers.length > 0 ? (
        <div className="card p-4">
          <div className="flex items-baseline justify-between">
            <p className="text-[13.5px] font-semibold">Session timeline</p>
            <p className="font-mono text-[11px] text-g400">
              {answers.length} questions
              {integrity.avg_answer_ms
                ? ` · ~${Math.round(integrity.avg_answer_ms / 1000)}s avg`
                : ""}
            </p>
          </div>
          <div className="mt-3 flex items-end gap-1.5">
            {answers.map((answer, index) => {
              const blurred = blurredQuestions.has(answer.question_id);
              const height = Math.max(
                12,
                Math.min(56, ((answer.response_ms ?? 0) / 1000) * 2.8),
              );
              return (
                <div key={answer.question_id} className="flex flex-1 flex-col items-center gap-1">
                  <div
                    title={`${answer.response_ms === null ? "no answer" : `${Math.round(answer.response_ms / 1000)}s`}${blurred ? " · off-screen time" : ""}`}
                    style={{ height }}
                    className={`w-full rounded-sm ${
                      blurred
                        ? "bg-amber-400/80 dark:bg-amber-500/70"
                        : "bg-g300/70 dark:bg-g600/70"
                    }`}
                  />
                  <span className="font-mono text-[10px] text-g400">Q{index + 1}</span>
                </div>
              );
            })}
          </div>
          <p className="mt-2 font-mono text-[10.5px] text-g400">
            bar height = answer time · amber = questions with off-screen time
          </p>
        </div>
      ) : null}

      {answers !== null && answers.some((answer) => answer.integrity_events.length > 0) ? (
        <div className="card p-4">
          <p className="text-[13.5px] font-semibold">Event log</p>
          <ul className="mt-2 space-y-1.5">
            {answers.flatMap((answer, index) =>
              answer.integrity_events.map((event, eventIndex) => (
                <li
                  key={`${answer.question_id}-${eventIndex}`}
                  className="flex items-center gap-3 text-[13px]"
                >
                  <span className="w-9 shrink-0 font-mono text-[11.5px] text-g500">
                    Q{index + 1}
                  </span>
                  <span className="flex-1">{EVENT_LABELS[event.type] ?? event.type}</span>
                  {event.duration_ms !== null && event.duration_ms > 0 ? (
                    <span className="inline-flex h-5 items-center rounded-full bg-muted-fill px-2 font-mono text-[10.5px] text-g600">
                      {Math.round(event.duration_ms / 1000)}s away
                    </span>
                  ) : null}
                </li>
              )),
            )}
          </ul>
        </div>
      ) : null}

      {flags.map((flag) => (
        <div
          key={flag.code}
          className="card border-l-[3px] border-l-amber-400 p-4 dark:border-l-amber-500"
        >
          <p className="text-[13.5px] font-semibold">{flag.summary}</p>
          <p className="mt-1 text-[13px] leading-[20px] text-g600">{flag.detail}</p>
        </div>
      ))}

      <div className="card p-4">
        <p className="text-[13.5px] font-semibold">How to read this</p>
        <ul className="mt-2 space-y-1 text-[13px] leading-[20px] text-g600">
          <li>
            · A blur can be an alt-tab, a notification, or a second-monitor glance — count alone
            isn&apos;t proof.
          </li>
          <li>· Resizes at question boundaries often mean window snapping (side-by-side reference).</li>
          <li>
            · Timing patterns matter more than totals. When in doubt, re-invite rather than
            reject.
          </li>
        </ul>
      </div>

      {attempt !== null ? (
        <div className="card flex flex-wrap items-center gap-2.5 p-4">
          <p className="mr-auto text-[13.5px] font-semibold">Decision</p>
          <button
            type="button"
            disabled={busy || reviewed}
            onClick={() => act(() => applications.dismissFlags(app.id), "Flags dismissed")}
            className="inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50"
          >
            {reviewed ? "Flags dismissed" : "Dismiss flags — looks fine"}
          </button>
          {confirming === "reissue" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                act(
                  () => applications.reissueQuiz(app.id),
                  `Fresh quiz sent to ${app.candidate.email}`,
                )
              }
              className="inline-flex h-8 items-center rounded-md bg-accent px-3 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
            >
              Confirm — invalidate this attempt and email a fresh quiz
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirming("reissue")}
              className="inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50"
            >
              Invalidate &amp; re-invite to a fresh quiz
            </button>
          )}
          {confirming === "reject" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                act(() => applications.setStage(app.id, "rejected"), "Application rejected")
              }
              className="inline-flex h-8 items-center rounded-md bg-red-600 px-3 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
            >
              Confirm reject
            </button>
          ) : (
            <button
              type="button"
              disabled={busy || app.stage === "rejected"}
              onClick={() => setConfirming("reject")}
              className="inline-flex h-8 items-center rounded-md px-3 text-[13px] font-medium text-red-600 hover:bg-muted-fill disabled:opacity-50 dark:text-red-400"
            >
              {app.stage === "rejected" ? "Rejected" : "Reject application…"}
            </button>
          )}
        </div>
      ) : null}
    </section>
  );
}
