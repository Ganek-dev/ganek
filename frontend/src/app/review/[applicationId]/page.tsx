"use client";

import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Avatar, Chip, SubmittedBody } from "@/components/ScorecardParts";
import { ScorecardForm } from "@/components/ScorecardForm";
import {
  ApiError,
  RECOMMENDATION_LABELS,
  review,
  scorecards,
  type ReviewApplicationOut,
  type ReviewQuizOutcome,
  type Scorecard,
} from "@/lib/api";
import { formatDateTime, relativeTime } from "@/lib/time";

/** The judging view (scorecards spec 5.2): name, job, CV, screening answers,
 * quiz summary, own interview, then the scorecard form. Everything is read
 * from GET /review/applications/{id} and re-read after every write, so
 * `others` and `hidden_until_submitted` always come from the server. Quiz
 * outcomes are information only: no pass/fail reading anywhere. */

const OUTCOME_LABELS: Record<ReviewQuizOutcome, string> = {
  correct: "Correct",
  wrong: "Wrong",
  timed_out: "Timed out",
  unanswered: "Unanswered",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <p className="font-mono text-[11px] tracking-[0.08em] text-g500 uppercase">{title}</p>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function answerText(answer: string | boolean | null): string {
  if (answer === null || answer === "") return "Not answered";
  if (answer === true) return "Yes";
  if (answer === false) return "No";
  if (answer === "yes") return "Yes";
  if (answer === "no") return "No";
  return answer;
}

function quizSummaryLine(quiz: NonNullable<ReviewApplicationOut["quiz"]>): string {
  const base = `${quiz.correct} of ${quiz.total} correct`;
  return quiz.timed_out > 0 ? `${base}, ${quiz.timed_out} timed out` : base;
}

function NotAvailable() {
  return (
    <div className="mx-auto max-w-[420px] py-12 text-center">
      <h1 className="font-heading text-[20px] font-semibold">This candidate is not available</h1>
      <p className="mt-2 text-[14px] leading-[21px] text-g600">
        You may no longer have access to this application.
      </p>
      <Link
        href="/review"
        className="mt-5 inline-flex items-center gap-1.5 text-[13.5px] font-semibold hover:text-accent"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Back to your candidates
      </Link>
    </div>
  );
}

function ReadOnlyCard({ row, onEdit }: { row: Scorecard; onEdit?: () => void }) {
  return (
    <div className="rounded-md border border-edge px-3 py-2">
      <div className="flex items-center gap-2">
        <Avatar label={row.reviewer_label} />
        <span className="text-[13px] font-medium">{row.reviewer_label}</span>
        {row.recommendation ? <Chip>{RECOMMENDATION_LABELS[row.recommendation]}</Chip> : null}
        <span className="ml-auto flex items-center gap-2 text-[11.5px] text-g500">
          {row.submitted_at ? relativeTime(row.submitted_at) : null}
          {row.edited ? " · edited" : null}
          {onEdit && row.can_edit ? (
            <button
              type="button"
              onClick={onEdit}
              className="font-medium text-foreground hover:underline"
            >
              Edit
            </button>
          ) : null}
        </span>
      </div>
      <SubmittedBody row={row} />
    </div>
  );
}

export default function ReviewDetailPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [data, setData] = useState<ReviewApplicationOut | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const fail = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 404) setMissing(true);
    else setError(err instanceof Error ? err.message : "Failed to load this candidate");
  }, []);

  // Re-read after every write: `others` and `hidden_until_submitted` come
  // from the server, never from the client.
  const load = useCallback(async () => {
    try {
      setData(await review.get(applicationId));
      setError(null);
    } catch (err) {
      fail(err);
    }
  }, [applicationId, fail]);

  useEffect(() => {
    let cancelled = false;
    review
      .get(applicationId)
      .then((out) => {
        if (!cancelled) setData(out);
      })
      .catch((err: unknown) => {
        if (!cancelled) fail(err);
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId, attempt, fail]);

  if (missing) return <NotAvailable />;
  if (error && !data) {
    return (
      <div role="alert" className="py-8">
        <p className="text-[14px] text-red-600 dark:text-red-400">{error}</p>
        <button
          type="button"
          onClick={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
          className="mt-3 inline-flex h-9 items-center rounded-md border-[1.5px] border-edge px-4 text-[13.5px] font-semibold hover:border-accent hover:text-accent"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!data) {
    return (
      <div aria-busy="true" className="space-y-3">
        {[0, 1, 2].map((n) => (
          <div
            key={n}
            data-testid="review-skeleton"
            className="h-24 animate-pulse rounded-md bg-muted-fill"
          />
        ))}
      </div>
    );
  }

  const { mine, interview, quiz } = data;

  return (
    <div>
      <Link
        href="/review"
        className="inline-flex items-center gap-1.5 text-[12.5px] text-g600 hover:text-accent"
      >
        <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
        Your candidates
      </Link>
      <h1 className="mt-3 font-heading text-[22px] font-semibold">{data.candidate_name}</h1>
      <p className="text-[14px] text-g600">{data.job_title}</p>

      {data.cv_url ? (
        <a
          href={data.cv_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex h-9 items-center gap-1.5 rounded-md border-[1.5px] border-edge px-3.5 text-[13.5px] font-semibold hover:border-accent hover:text-accent"
        >
          <ExternalLink aria-hidden className="h-4 w-4" />
          Open CV
        </a>
      ) : null}

      {data.screening_answers.length > 0 ? (
        <Section title="Screening answers">
          <ul className="divide-y divide-divider rounded-md border border-edge">
            {data.screening_answers.map((answer, index) => (
              <li key={index} className="px-3.5 py-2.5">
                <p className="text-[12.5px] text-g500">{answer.prompt}</p>
                <p className="text-sm">{answerText(answer.answer)}</p>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section title="Quiz">
        {quiz ? (
          <div>
            <p className="text-[14px] font-medium">
              {quizSummaryLine(quiz)}
              {quiz.score !== null ? (
                <span className="ml-2 font-mono text-[12.5px] font-normal text-g600">
                  {Math.round(quiz.score * 100)}%
                </span>
              ) : null}
            </p>
            <ul className="mt-2 divide-y divide-divider rounded-md border border-edge">
              {quiz.questions.map((question, index) => (
                <li key={index} className="flex items-center justify-between gap-3 px-3.5 py-2">
                  <span className="text-[13px]">{question.prompt}</span>
                  <Chip>{OUTCOME_LABELS[question.outcome]}</Chip>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-[13.5px] text-g600">No completed quiz</p>
        )}
      </Section>

      {interview ? (
        <Section title="Your interview">
          <p className="text-[14px]">
            {interview.scheduled_start
              ? `${formatDateTime(interview.scheduled_start, interview.timezone)} (${interview.timezone})`
              : "Time to be confirmed"}
            {" · "}
            {interview.duration_minutes} min
            {interview.location ? ` · ${interview.location}` : ""}
          </p>
        </Section>
      ) : null}

      {mine ? (
        <Section title="Your scorecard">
          {mine.state === "open" ? (
            <div className="rounded-md border border-edge p-3">
              <ScorecardForm
                criteria={mine.criteria}
                submitLabel="Submit scorecard"
                onSubmit={async (body) => {
                  await scorecards.submit(applicationId, body);
                  await load();
                }}
                onDecline={async () => {
                  await scorecards.decline(applicationId);
                  await load();
                }}
              />
            </div>
          ) : mine.state === "declined" ? (
            <p className="text-[13.5px] text-g600">You declined to assess this candidate.</p>
          ) : editing && mine.state === "submitted" ? (
            <div className="rounded-md border border-edge p-3">
              <ScorecardForm
                criteria={mine.criteria}
                initial={mine}
                submitLabel="Save changes"
                onSubmit={async (body) => {
                  await scorecards.submit(applicationId, body);
                  setEditing(false);
                  await load();
                }}
              />
            </div>
          ) : (
            <ReadOnlyCard row={mine} onEdit={() => setEditing(true)} />
          )}
        </Section>
      ) : null}

      {mine?.state === "open" && data.hidden_until_submitted ? (
        <p className="mt-4 text-[13px] text-g600">
          Colleagues&apos; scorecards appear after you submit yours.
        </p>
      ) : null}
      {data.others.length > 0 ? (
        <Section title="Colleagues">
          <ul className="space-y-2">
            {data.others.map((row) => (
              <li key={row.id}>
                <ReadOnlyCard row={row} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}
