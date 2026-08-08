"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AlertTriangle, BellRing, Check, ChevronDown, Clock, FileText, X } from "lucide-react";

import {
  api,
  applications,
  type ApplicationOut,
  type ApplicationStage,
  type IntegrityFlag,
  type JobOut,
  type QuizAnswerReview,
  type QuizResult,
  type ReviewIntegrityEvent,
} from "@/lib/api";
import { InterviewCard } from "@/components/InterviewCard";

/** Applicant review, handoff screen 11: split view — a 360px list of
 * candidates (score chips, flag dots, stage chip) beside a detail panel
 * with a score strip, per-question answers and an integrity card. Notes
 * and the "top N%" percentile stat need backend fields still on
 * feature branches, so they are intentionally omitted here. */

type StagePill = { value: ApplicationStage | "all"; label: string };

const STAGE_PILLS: StagePill[] = [
  { value: "all", label: "All" },
  { value: "new", label: "New" },
  { value: "screening", label: "Screening" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Offer" },
  { value: "hired", label: "Hired" },
  { value: "rejected", label: "Rejected" },
  { value: "withdrawn", label: "Withdrawn" },
];

const STAGE_ORDER: ApplicationStage[] = ["new", "screening", "interview", "offer", "hired"];

const SCORE_TONE = {
  green: {
    chip: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
    bar: "bg-emerald-200 dark:bg-emerald-900",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  amber: {
    chip: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
    bar: "bg-amber-200 dark:bg-amber-900",
    text: "text-amber-700 dark:text-amber-300",
  },
  red: {
    chip: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
    bar: "bg-red-200 dark:bg-red-900",
    text: "text-red-700 dark:text-red-400",
  },
  muted: {
    chip: "border-edge bg-muted-fill text-g500",
    bar: "bg-muted-fill",
    text: "text-g500",
  },
} as const;

function toneFor(percent: number): keyof typeof SCORE_TONE {
  if (percent >= 60) return "green";
  if (percent >= 40) return "amber";
  return "red";
}

function relativeTime(iso: string, now: Date = new Date()): string {
  const diff = now.getTime() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.round(days / 7);
  return `${weeks}w ago`;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

function ScoreChip({ result }: { result: QuizResult | null }) {
  if (!result || result.status !== "completed" || result.score === null) {
    return (
      <span className={`inline-flex h-[22px] items-center rounded-full px-2 font-mono text-xs ${SCORE_TONE.muted.chip}`}>
        —
      </span>
    );
  }
  const percent = Math.round(result.score * 100);
  const tone = SCORE_TONE[toneFor(percent)];
  return (
    <span
      className={`inline-flex h-[22px] items-center rounded-full border px-2 font-mono text-xs font-semibold ${tone.chip}`}
    >
      {percent}
    </span>
  );
}

function StagePill({ stage }: { stage: ApplicationStage }) {
  const cls =
    stage === "rejected"
      ? SCORE_TONE.red.chip
      : stage === "withdrawn"
        ? SCORE_TONE.muted.chip
      : stage === "hired" || stage === "offer"
        ? SCORE_TONE.green.chip
        : stage === "new"
          ? "border-accent/30 bg-accent/10 text-accent"
          : "border-edge bg-muted-fill text-g600";
  return (
    <span
      className={`inline-flex h-5 items-center rounded-full border px-2 text-[11px] font-medium ${cls}`}
    >
      {stage}
    </span>
  );
}

function ScoreStrip({
  result,
  answers,
}: {
  result: QuizResult;
  answers: QuizAnswerReview[] | null;
}) {
  const total = result.question_ids.length || answers?.length || 12;
  const percent = result.score === null ? null : Math.round(result.score * 100);
  const tone = percent === null ? SCORE_TONE.muted : SCORE_TONE[toneFor(percent)];

  // Segment source: prefer real answers if loaded; otherwise fall back to
  // the aggregate correct/wrong split, then a placeholder shape.
  let segments: Array<"correct" | "wrong" | "timeout"> = [];
  if (answers) {
    segments = answers.map((review) => {
      if (review.is_correct) return "correct";
      if (review.answer_key === null) return "timeout";
      return "wrong";
    });
  } else if (result.score !== null) {
    const correct = Math.round(result.score * total);
    segments = [
      ...Array<"correct">(correct).fill("correct"),
      ...Array<"wrong">(total - correct).fill("wrong"),
    ];
  }

  const counts = segments.reduce(
    (acc, kind) => ({ ...acc, [kind]: acc[kind] + 1 }),
    { correct: 0, wrong: 0, timeout: 0 },
  );

  const totalMs = answers?.reduce((sum, review) => sum + (review.response_ms ?? 0), 0) ?? 0;
  const totalDuration = totalMs > 0 ? formatDuration(totalMs / 1000) : null;
  const avgDuration =
    answers && answers.length > 0 && totalMs > 0
      ? formatDuration(totalMs / 1000 / answers.length)
      : null;

  return (
    <div className="mt-5 flex items-center gap-7 rounded-lg border border-divider px-5 py-4">
      <div>
        <div className={`font-heading text-4xl leading-none font-semibold ${tone.text}`}>
          {percent ?? "—"}
          {percent === null ? null : <span className="text-lg text-g500">%</span>}
        </div>
        <div className="mt-1.5 font-mono text-[10.5px] text-g500">
          {counts.correct + counts.wrong + counts.timeout > 0
            ? `${counts.correct} of ${total} correct`
            : "no answers recorded"}
        </div>
      </div>
      <div aria-hidden className="h-14 w-px self-stretch bg-divider" />
      <div className="flex-1">
        <div
          role="img"
          aria-label={`Per-question outcomes: ${counts.correct} correct, ${counts.wrong} wrong, ${counts.timeout} timed out`}
          className="flex gap-[3px]"
        >
          {segments.length === 0
            ? Array.from({ length: total }, (_, i) => (
                <span key={i} className="h-[22px] flex-1 rounded-sm bg-muted-fill" />
              ))
            : segments.map((kind, i) => (
                <span
                  key={i}
                  className={`h-[22px] flex-1 rounded-sm ${
                    kind === "correct"
                      ? SCORE_TONE.green.bar
                      : kind === "wrong"
                        ? SCORE_TONE.red.bar
                        : "bg-muted-fill"
                  }`}
                />
              ))}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-4 font-mono text-[10.5px] text-g500">
          <span>
            <span aria-hidden className={`mr-1.5 inline-block h-2 w-2 rounded-sm ${SCORE_TONE.green.bar}`} />
            {counts.correct} correct
          </span>
          <span>
            <span aria-hidden className={`mr-1.5 inline-block h-2 w-2 rounded-sm ${SCORE_TONE.red.bar}`} />
            {counts.wrong} wrong
          </span>
          <span>
            <span aria-hidden className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-muted-fill" />
            {counts.timeout} timed out
          </span>
          {totalDuration ? (
            <span className="ml-auto">
              total {totalDuration}
              {avgDuration ? ` · avg ${avgDuration}/q` : ""}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function eventLabel(event: ReviewIntegrityEvent): string {
  if (event.type === "blur") {
    const seconds =
      event.duration_ms !== null ? ` ${(event.duration_ms / 1000).toFixed(1)}s` : "";
    return `left the tab${seconds}`;
  }
  if (event.type === "paste") return "paste";
  return event.type;
}

function AnswerRow({ index, review }: { index: number; review: QuizAnswerReview }) {
  const candidate =
    review.answer_key === null ? null : review.options[review.answer_key];
  const timedOut = review.answer_key === null;
  const seconds =
    review.response_ms !== null ? formatDuration(review.response_ms / 1000) : "—";

  const Icon = review.is_correct ? Check : timedOut ? Clock : X;
  const iconTone = review.is_correct
    ? SCORE_TONE.green.text
    : timedOut
      ? "text-g400"
      : SCORE_TONE.red.text;

  return (
    <li className="flex items-start gap-3 border-b border-divider py-[11px] last:border-b-0">
      <span className="w-6 shrink-0 pt-0.5 font-mono text-[11px] text-g400">Q{index + 1}</span>
      <Icon aria-hidden className={`mt-0.5 h-[15px] w-[15px] shrink-0 ${iconTone}`} />
      <div className="min-w-0 flex-1">
        <p className={`text-[13.5px] font-medium ${timedOut ? "text-g500" : ""}`}>
          {review.prompt_md}
        </p>
        {timedOut ? (
          <p className="mt-1 text-xs text-g400">time ran out — no answer</p>
        ) : review.is_correct ? (
          <p className="mt-1 text-[12.5px] text-g600">
            answered: <span className="font-medium">{candidate}</span>
          </p>
        ) : (
          <p className="mt-1 text-[12.5px] text-g600">
            answered:{" "}
            <span className={SCORE_TONE.red.text}>{candidate}</span>
            {" · "}correct:{" "}
            <span className={`${SCORE_TONE.green.text} font-medium`}>
              {review.options[review.correct_key]}
            </span>
          </p>
        )}
        {review.integrity_events.length > 0 ? (
          <p className="mt-1 flex flex-wrap gap-2 font-mono text-[11px] text-amber-700 dark:text-amber-400">
            {review.integrity_events.map((event, i) => (
              <span key={i} className="inline-flex items-center gap-1">
                <AlertTriangle aria-hidden className="h-3 w-3" />
                {eventLabel(event)}
              </span>
            ))}
          </p>
        ) : null}
        {review.explanation_md ? (
          <p className="mt-1 text-xs text-g500">{review.explanation_md}</p>
        ) : null}
      </div>
      <span className="shrink-0 font-mono text-[11px] text-g400">{seconds}</span>
    </li>
  );
}

function IntegrityCard({ result, applicationId }: { result: QuizResult; applicationId: string }) {
  const flags = result.integrity.flags ?? [];
  const risk = flags.length === 0 ? "low" : flags.length === 1 ? "some" : "high";
  const tone = risk === "low" ? SCORE_TONE.green.chip : SCORE_TONE.amber.chip;

  return (
    <div className="rounded-lg border border-divider p-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] tracking-[0.08em] text-g500 uppercase">
          Integrity
        </span>
        <span className="flex items-center gap-2">
          <span className={`inline-flex h-5 items-center rounded-full border px-2 text-[11px] font-medium ${tone}`}>
            {risk === "low" ? "low risk" : `${flags.length} flag${flags.length > 1 ? "s" : ""}`}
          </span>
          <Link
            href={`/admin/applicants/${applicationId}/integrity`}
            className="text-[11.5px] font-medium text-accent hover:underline"
          >
            Review →
          </Link>
        </span>
      </div>
      {result.integrity.reissue_requested ? (
        <p className="mt-2.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[12px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          Candidate&apos;s link expired — they requested a new one
          {result.integrity.reissue_requested.count > 1
            ? ` (×${result.integrity.reissue_requested.count})`
            : ""}
          . Re-issue from the review page.
        </p>
      ) : null}
      {result.integrity.reissue ? (
        <p className="mt-2.5 text-[12px] text-g500">
          Fresh quiz — re-issued after{" "}
          {result.integrity.reissue.reason === "expired"
            ? "the previous link expired"
            : "an integrity review"}
          {result.integrity.reissue.mode === "auto" ? " (automatic)" : ""}.
        </p>
      ) : null}
      {flags.length === 0 ? (
        <p className="mt-2.5 text-[12.5px] leading-[19px] text-g600">
          No integrity events detected during the quiz.
        </p>
      ) : (
        <ul className="mt-2.5 space-y-2 text-[12.5px] leading-[19px] text-g600">
          {flags.map((flag: IntegrityFlag) => (
            <li key={flag.code}>
              <p className="font-medium">{flag.summary}</p>
              <p className="text-g500">{flag.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DetailPanel({
  app,
  jobTitle,
  answers,
  onStage,
  onDownloadCv,
  onRemind,
  now,
}: {
  app: ApplicationOut;
  jobTitle: string;
  answers: QuizAnswerReview[] | null;
  onStage: (stage: ApplicationStage, notify: boolean) => void;
  onDownloadCv: () => void;
  onRemind: () => Promise<boolean>;
  now: Date;
}) {
  const [notify, setNotify] = useState(false);
  const [reminded, setReminded] = useState(false);
  const nextStage = useMemo(() => {
    const currentIndex = STAGE_ORDER.indexOf(app.stage);
    if (currentIndex < 0 || currentIndex >= STAGE_ORDER.length - 1) return null;
    return STAGE_ORDER[currentIndex + 1];
  }, [app.stage]);

  return (
    <div className="card p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="font-heading text-[19px] font-semibold">{app.candidate.name}</h2>
            <StagePill stage={app.stage} />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-3.5 text-[13px] text-g600">
            <span className="font-mono text-xs">{app.candidate.email}</span>
            <button
              type="button"
              onClick={onDownloadCv}
              className="inline-flex items-center gap-1.5 font-medium text-accent hover:underline"
            >
              <FileText aria-hidden className="h-[13px] w-[13px]" />
              {app.cv_filename} ({formatBytes(app.cv_size)})
            </button>
            <span className="font-mono text-[11.5px] text-g400">
              {jobTitle} · applied {relativeTime(app.created_at, now)}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            {nextStage && app.stage !== "rejected" && app.stage !== "withdrawn" ? (
              <button
                type="button"
                onClick={() => onStage(nextStage, notify)}
                className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13.5px] font-semibold text-white hover:brightness-[0.94]"
              >
                Advance
              </button>
            ) : null}
            {app.stage !== "rejected" && app.stage !== "withdrawn" ? (
              <button
                type="button"
                onClick={() => onStage("rejected", notify)}
                className={`inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[13.5px] font-medium hover:bg-muted-fill ${SCORE_TONE.red.text}`}
              >
                Reject
              </button>
            ) : null}
            <label className="sr-only" htmlFor={`stage-${app.id}`}>
              {`Stage for ${app.candidate.name}`}
            </label>
            <div className="relative">
              <select
                id={`stage-${app.id}`}
                value={app.stage}
                onChange={(event) => onStage(event.target.value as ApplicationStage, notify)}
                className="inline-flex h-8 appearance-none items-center rounded-md border border-edge bg-surface pr-7 pl-3 text-[13px] font-medium text-g700 outline-none focus:border-g400"
              >
                {STAGE_ORDER.concat("rejected").map((stage) => (
                  <option key={stage} value={stage}>
                    Stage: {stage}
                  </option>
                ))}
              </select>
              <ChevronDown
                aria-hidden
                className="pointer-events-none absolute top-1/2 right-2 h-3.5 w-3.5 -translate-y-1/2 text-g500"
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            {app.quiz_attempt?.status === "pending" ? (
              reminded ? (
                <span className="font-mono text-[11px] text-g500">Reminder sent</span>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    void onRemind().then((ok) => {
                      if (ok) setReminded(true);
                    });
                  }}
                  className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-accent hover:underline"
                >
                  <BellRing aria-hidden className="h-3 w-3" />
                  Send reminder
                </button>
              )
            ) : null}
            <label className="flex cursor-pointer items-center gap-1.5 text-[12.5px] text-g600">
              <input
                type="checkbox"
                checked={notify}
                onChange={(event) => setNotify(event.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--color-accent)]"
              />
              Email the candidate
              <span className="font-mono text-[10.5px] text-g400">interview · rejection</span>
            </label>
          </div>
        </div>
      </div>

      {app.message ? (
        <p className="mt-4 text-sm text-g600">{app.message}</p>
      ) : null}

      {app.stage !== "rejected" && app.stage !== "withdrawn" ? (
        <div className="mt-4">
          <InterviewCard key={app.id} applicationId={app.id} />
        </div>
      ) : null}

      {app.quiz_attempt && app.quiz_attempt.status === "completed" ? (
        <>
          <ScoreStrip result={app.quiz_attempt} answers={answers} />
          <p className="mt-5 font-mono text-[11px] tracking-[0.08em] text-g500 uppercase">
            Answers
          </p>
          {answers === null ? (
            <div aria-busy="true" className="mt-2 space-y-2">
              {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-sm bg-muted-fill" />
              ))}
            </div>
          ) : (
            <ol className="mt-2">
              {answers.map((review, index) => (
                <AnswerRow key={review.question_id} index={index} review={review} />
              ))}
            </ol>
          )}
          <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <IntegrityCard result={app.quiz_attempt} applicationId={app.id} />
          </div>
        </>
      ) : app.quiz_attempt ? (
        <p className="mt-5 text-sm text-g500">
          Quiz {app.quiz_attempt.status.replace("_", " ")}.
        </p>
      ) : (
        <p className="mt-5 text-sm text-g500">This job did not include a screening quiz.</p>
      )}

      {Object.keys(app.candidate.links).length > 0 ? (
        <p className="mt-5 flex flex-wrap gap-4 text-sm">
          {Object.entries(app.candidate.links).map(([kind, url]) => (
            <a
              key={kind}
              href={url}
              rel="noopener noreferrer"
              target="_blank"
              className="text-g600 underline hover:text-accent"
            >
              {kind}
            </a>
          ))}
        </p>
      ) : null}
    </div>
  );
}

export default function ApplicantsPage() {
  const [items, setItems] = useState<ApplicationOut[] | null>(null);
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [stageFilter, setStageFilter] = useState<ApplicationStage | "all">("all");
  const [jobFilter, setJobFilter] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [answersById, setAnswersById] = useState<Record<string, QuizAnswerReview[]>>({});
  const loadingAnswersFor = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const reload = useCallback(() => {
    applications
      .list({
        stage: stageFilter === "all" ? undefined : stageFilter,
        job_id: jobFilter === "" ? undefined : jobFilter,
      })
      .then((rows) => {
        setItems(rows);
        setSelectedId((current) => {
          if (current && rows.some((row) => row.id === current)) return current;
          return rows[0]?.id ?? null;
        });
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load applications"),
      );
  }, [stageFilter, jobFilter]);

  useEffect(reload, [reload]);

  useEffect(() => {
    api.jobs
      .list()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    if (
      selectedId === null ||
      answersById[selectedId] !== undefined ||
      loadingAnswersFor.current === selectedId
    ) {
      return;
    }
    const target = items?.find((app) => app.id === selectedId);
    if (!target || target.quiz_attempt?.status !== "completed") return;
    const id = selectedId;
    loadingAnswersFor.current = id;
    applications
      .quizAnswers(id)
      .then((reviews) => setAnswersById((prev) => ({ ...prev, [id]: reviews })))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load answers"),
      )
      .finally(() => {
        if (loadingAnswersFor.current === id) loadingAnswersFor.current = null;
      });
  }, [selectedId, items, answersById]);

  const jobLookup = useMemo(
    () => Object.fromEntries(jobs.map((job) => [job.id, job.title])),
    [jobs],
  );

  const counts = useMemo(() => {
    const base: Record<StagePill["value"], number> = {
      all: items?.length ?? 0,
      new: 0,
      screening: 0,
      interview: 0,
      offer: 0,
      hired: 0,
      rejected: 0,
      withdrawn: 0,
    };
    for (const app of items ?? []) base[app.stage] += 1;
    return base;
  }, [items]);

  async function changeStage(id: string, stage: ApplicationStage, notify: boolean) {
    setError(null);
    try {
      await applications.setStage(id, stage, notify);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stage change failed");
    }
  }

  async function remindCandidate(id: string): Promise<boolean> {
    setError(null);
    try {
      await applications.remind(id);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reminder failed");
      return false;
    }
  }

  async function downloadCv(id: string) {
    setError(null);
    try {
      const { download_url } = await applications.cvUrl(id);
      window.open(download_url, "_blank", "noopener");
    } catch (err) {
      setError(err instanceof Error ? err.message : "CV download failed");
    }
  }

  const selected = items?.find((app) => app.id === selectedId) ?? null;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Applicants</h1>
        <div className="relative">
          <select
            aria-label="Filter by job"
            value={jobFilter}
            onChange={(event) => setJobFilter(event.target.value)}
            className="inline-flex h-[34px] appearance-none items-center rounded-md border border-edge bg-surface pr-8 pl-3 text-[13px] text-g700 outline-none focus:border-g400"
          >
            <option value="">All jobs</option>
            {jobs.map((job) => (
              <option key={job.id} value={job.id}>
                {job.title}
              </option>
            ))}
          </select>
          <ChevronDown
            aria-hidden
            className="pointer-events-none absolute top-1/2 right-2.5 h-3.5 w-3.5 -translate-y-1/2 text-g500"
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {STAGE_PILLS.map((pill) => (
          <button
            key={pill.value}
            type="button"
            aria-pressed={stageFilter === pill.value}
            onClick={() => setStageFilter(pill.value)}
            className={`inline-flex h-7 items-center rounded-full px-[11px] text-[12.5px] font-medium ${
              stageFilter === pill.value
                ? "bg-inverse text-inverse-foreground"
                : "border border-edge bg-surface text-g700 hover:border-g400"
            }`}
          >
            {pill.label} · {counts[pill.value]}
          </button>
        ))}
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[360px_1fr]">
        <div className="card overflow-hidden">
          {items === null ? (
            <div aria-busy="true" className="p-3">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="mb-2 h-14 animate-pulse rounded-sm bg-muted-fill" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <p className="p-4 text-sm text-g500">No applications match.</p>
          ) : (
            <ul>
              {items.map((app) => {
                const isSelected = selectedId === app.id;
                const hasFlags = (app.quiz_attempt?.integrity.flags?.length ?? 0) > 0;
                return (
                  <li key={app.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(app.id)}
                      aria-current={isSelected ? "true" : undefined}
                      className={`flex w-full items-center gap-3 border-t border-divider px-4 py-[13px] text-left first:border-t-0 ${
                        isSelected
                          ? "border-l-[3px] border-l-accent bg-accent/[0.06]"
                          : "border-l-[3px] border-l-transparent hover:bg-hover-fill"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`truncate text-sm ${isSelected ? "font-semibold" : "font-medium"}`}
                          >
                            {app.candidate.name}
                          </span>
                          {hasFlags ? (
                            <span
                              aria-label="integrity flag"
                              title="integrity flag"
                              className="h-[7px] w-[7px] shrink-0 rounded-full bg-amber-500"
                            />
                          ) : null}
                        </div>
                        <p className="mt-0.5 font-mono text-[11px] text-g500">
                          applied {relativeTime(app.created_at, now)} · {app.stage}
                        </p>
                      </div>
                      <ScoreChip result={app.quiz_attempt} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {selected ? (
          <DetailPanel
            key={selected.id}
            app={selected}
            jobTitle={jobLookup[selected.job_id] ?? "—"}
            answers={answersById[selected.id] ?? null}
            onStage={(stage, notify) => changeStage(selected.id, stage, notify)}
            onDownloadCv={() => downloadCv(selected.id)}
            onRemind={() => remindCandidate(selected.id)}
            now={now}
          />
        ) : items === null ? (
          <div className="card h-[540px] animate-pulse" />
        ) : (
          <div className="card flex h-[540px] items-center justify-center p-6 text-sm text-g500">
            Select an applicant to review.
          </div>
        )}
      </div>
    </section>
  );
}
