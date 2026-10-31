"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  Check,
  ChevronDown,
  Clock,
  Download,
  Mail,
  FileText,
  X,
} from "lucide-react";

import {
  api,
  applications,
  emailTemplates,
  type ApplicationOut,
  type ApplicationStage,
  type MessageInput,
  type EmailKind,
  type EmailKindInfo,
  type EmailTemplate,
  type StageFields,
  type IntegrityFlag,
  type JobOut,
  type QuizAnswerReview,
  type QuizResult,
  type ReviewIntegrityEvent,
} from "@/lib/api";
import {
  clearNarrowing,
  countActive,
  filtersToParams,
  parseFilters,
  toApiFilters,
  type ApplicantFilters,
  type SortKey,
} from "@/lib/applicant-filters";
import { relativeTime } from "@/lib/time";
import { SCORE_TONE, ScoreChip, StagePill, toneFor } from "@/components/ApplicantChips";
import { MessageDialog } from "@/components/MessageDialog";
import { BUILTIN_TEMPLATE, REASON_HELPER, StageEmailDialog } from "@/components/StageEmailDialog";
import { REJECTION_REASONS, type RejectionReason } from "@/lib/rejection-reasons";
import { ApplicantFilterBar } from "@/components/ApplicantFilterBar";
import { InterviewCard } from "@/components/InterviewCard";
import { AccessTrailCard } from "@/components/AccessTrailCard";
import { NotesCard } from "@/components/NotesCard";
import { TimelineCard } from "@/components/TimelineCard";
import { Toast, type ToastMessage } from "@/components/Toast";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Menu, MenuContent, MenuDotsTrigger, MenuItem } from "@/components/ui/menu";

/** Applicant review, handoff screen 11: split view - a 360px list of
 * candidates (score chips, flag dots, stage chip) beside a detail panel
 * with a score strip, per-question answers, an integrity card, and internal
 * notes. The "top N%" percentile stat needs a backend field still on a
 * feature branch, so it is intentionally omitted here. */

type StagePill = { value: ApplicationStage | "all"; label: string };

const LIST_PAGE_SIZE = 50;
/** Server cap on bulk reject, bulk stage and the export selection. */
const BULK_CAP = 100;

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

const SORT_OPTIONS: Array<{ value: SortKey; label: string }> = [
  { value: "applied_desc", label: "Newest first" },
  { value: "applied_asc", label: "Oldest first" },
  { value: "score_desc", label: "Score: high to low" },
  { value: "score_asc", label: "Score: low to high" },
  { value: "name_asc", label: "Name A to Z" },
  { value: "stage_age_desc", label: "Longest in stage" },
  { value: "stage_age_asc", label: "Shortest in stage" },
];

const STAGE_LABELS: Record<ApplicationStage, string> = {
  new: "New",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

/** "in screening for 4d": how long the row has sat in its current stage. */
function stageAge(app: ApplicationOut, now: Date): string {
  const age = relativeTime(app.stage_changed_at, now);
  if (age === "just now") return `moved to ${app.stage} just now`;
  return `in ${app.stage} for ${age.replace(" ago", "")}`;
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
          {percent ?? "-"}
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

function templatesOf(kinds: EmailKindInfo[] | null, kind: EmailKindInfo["kind"]): EmailTemplate[] {
  return kinds?.find((entry) => entry.kind === kind)?.templates ?? [];
}

/** The kind's default template id, the Ganek default when custom templates
 * exist without a default, "" when there are none (nothing is sent). */
function defaultChoice(kinds: EmailKindInfo[], kind: EmailKindInfo["kind"]): string {
  const own = templatesOf(kinds, kind);
  if (own.length === 0) return "";
  return own.find((t) => t.is_default)?.id ?? BUILTIN_TEMPLATE;
}

function templateName(templates: EmailTemplate[], value: string): string {
  return templates.find((t) => t.id === value)?.name ?? "Ganek default";
}

function TemplateSelect({
  label,
  value,
  templates,
  onChange,
}: {
  label: string;
  value: string;
  templates: EmailTemplate[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[12.5px] text-g600">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-7 rounded-sm border border-edge bg-surface px-1.5 text-[12.5px] text-foreground"
      >
        <option value={BUILTIN_TEMPLATE}>Ganek default</option>
        {templates.map((template) => (
          <option key={template.id} value={template.id}>
            {template.name}
          </option>
        ))}
      </select>
    </label>
  );
}

type BulkPreviewState =
  | { kind: "loading" }
  | { kind: "ready"; subject: string; text: string }
  | { kind: "error" };

/** The rejection email as the first selected candidate would receive it
 * (card "Candidate emails", PR 3): every candidate gets their own values. */
function BulkPreview({
  kind,
  label,
  applicationId,
  candidateName,
  templateId,
}: {
  kind: EmailKind;
  label: string;
  applicationId: string;
  candidateName: string;
  templateId: string | undefined;
}) {
  const [fetched, setFetched] = useState<{ key: string; state: BulkPreviewState } | null>(null);
  const key = `${kind}:${applicationId}:${templateId ?? ""}`;

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      applications
        .emailPreview(applicationId, kind, templateId)
        .then((preview) => {
          if (!cancelled) {
            setFetched({
              key,
              state: { kind: "ready", subject: preview.subject, text: preview.text },
            });
          }
        })
        .catch(() => {
          if (!cancelled) setFetched({ key, state: { kind: "error" } });
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [applicationId, kind, templateId, key]);

  const state: BulkPreviewState =
    fetched !== null && fetched.key === key ? fetched.state : { kind: "loading" };
  return (
    <div className="space-y-1">
      <p className="text-[11.5px] text-g500">
        {label}. Shown for {candidateName}; each candidate gets their own values.
      </p>
      {state.kind === "loading" ? (
        <div aria-busy="true" aria-label="Loading preview" className="space-y-1.5">
          <div className="h-4 w-56 animate-pulse rounded-sm bg-muted-fill" />
          <div className="h-16 animate-pulse rounded-md bg-muted-fill" />
        </div>
      ) : state.kind === "error" ? (
        <p className="text-[12px] text-g600">
          Preview unavailable. The emails are still sent when you confirm.
        </p>
      ) : (
        <>
          <p className="text-[12.5px] text-g600">
            Subject: <span className="font-medium text-foreground">{state.subject}</span>
          </p>
          <pre
            data-testid="bulk-email-text"
            className="max-h-40 overflow-auto rounded-md border border-edge bg-muted-fill p-2 font-mono text-[11.5px] leading-[17px] whitespace-pre-wrap text-g700"
          >
            {state.text}
          </pre>
        </>
      )}
    </div>
  );
}

function BulkActionBar({
  selected,
  onClear,
  onChanged,
}: {
  selected: Map<string, string>;
  onClear: () => void;
  onChanged: () => void;
}) {
  const [notify, setNotify] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // the internal rejection reason for every row (PR 2); never emailed
  const [bulkReason, setBulkReason] = useState<RejectionReason | "">("");
  const [bulkNote, setBulkNote] = useState("");
  // the workspace's email templates (PR 3), listed once the checkbox is on;
  // "" = no custom template for that kind, so nothing is sent
  const [kinds, setKinds] = useState<EmailKindInfo[] | null>(null);
  const [rejectTemplate, setRejectTemplate] = useState("");
  const [interviewTemplate, setInterviewTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  useEffect(() => {
    if (flash === null) return;
    const id = setTimeout(() => setFlash(null), 3000);
    return () => clearTimeout(id);
  }, [flash]);

  useEffect(() => {
    if (!notify || kinds !== null) return;
    let cancelled = false;
    emailTemplates
      .list()
      .then((data) => {
        if (cancelled) return;
        setKinds(data.kinds);
        setRejectTemplate(defaultChoice(data.kinds, "rejection"));
        setInterviewTemplate(defaultChoice(data.kinds, "stage_advance"));
      })
      .catch(() => {
        if (!cancelled) setKinds([]);
      });
    return () => {
      cancelled = true;
    };
  }, [notify, kinds]);

  if (selected.size === 0 && flash === null) return null;
  const rejectionTemplates = templatesOf(kinds, "rejection");
  const advanceTemplates = templatesOf(kinds, "stage_advance");

  const ids = Array.from(selected.keys());
  const names = Array.from(selected.values());
  const namesLine =
    names.length > 5
      ? `${names.slice(0, 5).join(", ")} and ${names.length - 5} more`
      : names.join(", ");
  const tooMany = selected.size > BULK_CAP;

  async function confirmReject() {
    setBusy(true);
    setError(null);
    try {
      const fields: StageFields = {
        rejectionReason: bulkReason || null,
        rejectionNote: bulkNote.trim() || null,
      };
      if (notify && rejectTemplate) fields.templateId = rejectTemplate;
      const { rejected } = await applications.bulkReject(ids, notify, fields);
      setConfirming(false);
      setBulkReason("");
      setBulkNote("");
      setFlash(`Rejected ${rejected}`);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk reject failed");
    } finally {
      setBusy(false);
    }
  }

  async function move(stage: ApplicationStage) {
    setBusy(true);
    setError(null);
    try {
      const { updated, skipped } =
        stage === "interview" && notify && interviewTemplate
          ? await applications.bulkStage(ids, stage, notify, { templateId: interviewTemplate })
          : await applications.bulkStage(ids, stage, notify);
      setFlash(skipped > 0 ? `Moved ${updated}, skipped ${skipped}` : `Moved ${updated}`);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk move failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sticky bottom-0 z-10 space-y-2 border-t border-edge bg-surface p-2.5 shadow-[0_-6px_12px_-8px_rgba(0,0,0,0.25)]">
      {selected.size > 0 ? (
        confirming ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="text-[12.5px] text-g600">
                Reject {selected.size} applicant{selected.size === 1 ? "" : "s"}?
              </span>
              <span className="truncate text-[11.5px] text-g500" title={namesLine}>
                {namesLine}
              </span>
              {notify ? (
                <span className="text-[11.5px] text-g500">
                  Email: {templateName(rejectionTemplates, rejectTemplate)}
                </span>
              ) : null}
            </span>
            <div className="flex w-full flex-col gap-1.5">
              <label className="text-[12px] font-medium text-g700">
                Reason (internal, optional)
                <select
                  value={bulkReason}
                  onChange={(event) => setBulkReason(event.target.value as RejectionReason | "")}
                  className="mt-1 block h-7 w-full rounded-sm border border-edge bg-surface px-1.5 text-[12.5px] font-normal text-foreground"
                >
                  <option value="">No reason recorded</option>
                  {REJECTION_REASONS.filter((reason) => reason.key !== "withdrew").map((reason) => (
                    <option key={reason.key} value={reason.key}>
                      {reason.label}
                    </option>
                  ))}
                </select>
              </label>
              <input
                type="text"
                aria-label="Internal note"
                value={bulkNote}
                onChange={(event) => setBulkNote(event.target.value)}
                placeholder="Internal note (optional)"
                maxLength={1000}
                className="h-7 w-full rounded-sm border border-edge bg-surface px-1.5 text-[12.5px] text-foreground placeholder:text-g500"
              />
              <p className="text-[11px] text-g500">{REASON_HELPER}</p>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => void confirmReject()}
              className="inline-flex h-7 items-center rounded-sm bg-red-600 px-2.5 text-[12.5px] font-medium text-white hover:brightness-[0.94] disabled:opacity-50"
            >
              {busy ? "…" : "Yes, reject"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                // Cancel discards: a note about this set must not arm the next
                setConfirming(false);
                setBulkReason("");
                setBulkNote("");
              }}
              className="inline-flex h-7 items-center rounded-sm border border-edge bg-surface px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50"
            >
              Keep them
            </button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-semibold">{selected.size} selected</span>
              <div className="relative">
                <select
                  aria-label="Move selected to stage"
                  value=""
                  disabled={busy || tooMany}
                  onChange={(event) => {
                    const stage = event.target.value as ApplicationStage | "";
                    if (stage !== "") void move(stage);
                  }}
                  className="inline-flex h-7 appearance-none items-center rounded-sm border border-edge bg-surface pr-7 pl-2.5 text-[12.5px] font-medium text-g700 outline-none hover:bg-muted-fill focus:border-g400 disabled:opacity-50"
                >
                  <option value="">Move to…</option>
                  {STAGE_ORDER.map((stage) => (
                    <option key={stage} value={stage}>
                      {stage}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  aria-hidden
                  className="pointer-events-none absolute top-1/2 right-2 h-3.5 w-3.5 -translate-y-1/2 text-g500"
                />
              </div>
              <button
                type="button"
                disabled={busy || tooMany}
                onClick={() => setConfirming(true)}
                className={`inline-flex h-7 items-center rounded-sm border border-edge bg-surface px-2.5 text-[12.5px] font-medium hover:bg-muted-fill disabled:opacity-50 ${SCORE_TONE.red.text}`}
              >
                Reject…
              </button>
              <button
                type="button"
                onClick={onClear}
                className="ml-auto text-[12.5px] text-g500 hover:underline"
              >
                Clear
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <a
                href={applications.exportUrl("csv", { ids })}
                download
                aria-disabled={tooMany || undefined}
                className="inline-flex h-7 items-center gap-1.5 rounded-sm border border-edge bg-surface px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill aria-disabled:pointer-events-none aria-disabled:opacity-50"
              >
                <Download aria-hidden className="h-3.5 w-3.5" />
                Export selected (CSV)
              </a>
              <label className="flex cursor-pointer items-center gap-1.5 text-[12.5px] text-g600">
                <input
                  type="checkbox"
                  checked={notify}
                  onChange={(event) => setNotify(event.target.checked)}
                  className="h-3.5 w-3.5 accent-[var(--color-accent)]"
                />
                Also email candidates
              </label>
              {notify && rejectionTemplates.length > 0 ? (
                <TemplateSelect
                  label="Rejection template"
                  value={rejectTemplate}
                  templates={rejectionTemplates}
                  onChange={setRejectTemplate}
                />
              ) : null}
              {notify && advanceTemplates.length > 0 ? (
                <TemplateSelect
                  label="Interview template"
                  value={interviewTemplate}
                  templates={advanceTemplates}
                  onChange={setInterviewTemplate}
                />
              ) : null}
              {tooMany ? (
                <span className="text-[11.5px] text-warn">
                  Up to {BULK_CAP} at a time - narrow the selection.
                </span>
              ) : null}
            </div>
            {notify && kinds !== null && ids.length > 0 ? (
              <>
                <BulkPreview
                  kind="rejection"
                  label="Rejection email"
                  applicationId={ids[0]}
                  candidateName={names[0]}
                  templateId={rejectTemplate || undefined}
                />
                <BulkPreview
                  kind="stage_advance"
                  label="Interview email"
                  applicationId={ids[0]}
                  candidateName={names[0]}
                  templateId={interviewTemplate || undefined}
                />
              </>
            ) : null}
          </>
        )
      ) : null}
      {flash !== null ? (
        <span
          role="status"
          className="inline-flex items-center gap-1 text-[12.5px] text-emerald-700 dark:text-emerald-400"
        >
          <Check aria-hidden className="h-3.5 w-3.5" />
          {flash}
        </span>
      ) : null}
      {error ? (
        <span role="alert" className="text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </span>
      ) : null}
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
    review.response_ms !== null ? formatDuration(review.response_ms / 1000) : "-";

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
          <p className="mt-1 text-xs text-g400">time ran out - no answer</p>
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
            Review
            <ArrowRight aria-hidden className="ml-0.5 inline h-3 w-3 align-[-1px]" />
          </Link>
        </span>
      </div>
      {result.integrity.reissue_requested ? (
        <p className="mt-2.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[12px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          Candidate&apos;s link expired - they requested a new one
          {result.integrity.reissue_requested.count > 1
            ? ` (×${result.integrity.reissue_requested.count})`
            : ""}
          . Re-issue from the review page.
        </p>
      ) : null}
      {result.integrity.reissue ? (
        <p className="mt-2.5 text-[12px] text-g500">
          Fresh quiz - re-issued after{" "}
          {result.integrity.reissue.reason === "expired"
            ? "the previous link expired"
            : result.integrity.reissue.reason === "accommodation"
              ? "extra time was granted"
              : "an integrity review"}
          {result.integrity.reissue.mode === "auto" ? " (automatic)" : ""}.
        </p>
      ) : null}
      {result.integrity.accommodation ? (
        <p className="mt-2.5 text-[12px] text-g500">
          Extra time granted: {result.integrity.accommodation.time_multiplier}x the usual limit
          per question.
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
  onExport,
  onErase,
  onUpdateEmail,
  onSendMessage,
  now,
  trailTick,
}: {
  app: ApplicationOut;
  jobTitle: string;
  answers: QuizAnswerReview[] | null;
  onStage: (stage: ApplicationStage, notify: boolean, fields?: StageFields) => void;
  onDownloadCv: () => void;
  onRemind: () => Promise<boolean>;
  onExport: () => void;
  onErase: () => Promise<boolean>;
  onUpdateEmail: (email: string) => Promise<string | null>;
  /** A one-off message (PR 4): resolves to an error to show, or null. */
  onSendMessage: (fields: MessageInput) => Promise<string | null>;
  now: Date;
  trailTick: number;
}) {
  const [notify, setNotify] = useState(false);
  // Reject always goes through the dialog (the internal reason, PR 2, plus
  // the email preview when the checkbox is on); interview shows the email
  // it sends when the checkbox is on; other stages have no mail
  const [dialog, setDialog] = useState<{ stage: "interview" | "rejected"; email: boolean } | null>(
    null,
  );
  function requestStage(stage: ApplicationStage) {
    if (stage === "rejected") {
      setDialog({ stage, email: notify });
      return;
    }
    if (notify && stage === "interview") {
      setDialog({ stage, email: true });
      return;
    }
    onStage(stage, notify);
  }
  const [reminded, setReminded] = useState(false);
  const [confirmingErase, setConfirmingErase] = useState(false);
  const [eraseBusy, setEraseBusy] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  // "Send a message" (PR 4): the counter re-keys the dialog per opening
  const [messageOpen, setMessageOpen] = useState(false);
  const [messageOpening, setMessageOpening] = useState(0);
  const [emailDraft, setEmailDraft] = useState(app.candidate.email);
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);
  const nextStage = useMemo(() => {
    const currentIndex = STAGE_ORDER.indexOf(app.stage);
    if (currentIndex < 0 || currentIndex >= STAGE_ORDER.length - 1) return null;
    return STAGE_ORDER[currentIndex + 1];
  }, [app.stage]);

  async function confirmErase() {
    setEraseBusy(true);
    try {
      await onErase();
    } finally {
      setEraseBusy(false);
      setConfirmingErase(false);
    }
  }

  async function saveEmail(event: React.FormEvent) {
    event.preventDefault();
    if (emailBusy) return;
    setEmailBusy(true);
    setEmailError(null);
    const failure = await onUpdateEmail(emailDraft);
    setEmailBusy(false);
    if (failure !== null) setEmailError(failure);
    else setEmailOpen(false);
  }

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
              {app.source ? ` · via ${app.source}` : ""}
              {app.stage_changed_at !== app.created_at ? ` · ${stageAge(app, now)}` : ""}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="flex items-center gap-2">
            {nextStage && app.stage !== "rejected" && app.stage !== "withdrawn" ? (
              <button
                type="button"
                onClick={() => requestStage(nextStage)}
                className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13.5px] font-semibold text-white hover:brightness-[0.94]"
              >
                Advance
              </button>
            ) : null}
            {app.stage !== "rejected" && app.stage !== "withdrawn" ? (
              <button
                type="button"
                onClick={() => requestStage("rejected")}
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
                onChange={(event) => requestStage(event.target.value as ApplicationStage)}
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
            <Menu>
              <MenuDotsTrigger
                label="More actions"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-edge bg-surface text-g500 hover:bg-muted-fill data-[state=open]:bg-muted-fill"
              />
              <MenuContent className="w-52">
                <MenuItem onSelect={onExport}>Export data (JSON)</MenuItem>
                <MenuItem
                  onSelect={() => {
                    setEmailDraft(app.candidate.email);
                    setEmailError(null);
                    setEmailOpen(true);
                  }}
                >
                  Edit candidate email…
                </MenuItem>
                <MenuItem onSelect={() => setConfirmingErase(true)} className="text-danger">
                  Erase candidate…
                </MenuItem>
              </MenuContent>
            </Menu>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                setMessageOpening((n) => n + 1);
                setMessageOpen(true);
              }}
              className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-accent hover:underline"
            >
              <Mail aria-hidden className="h-3 w-3" />
              Send a message
            </button>
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

      {confirmingErase ? (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-edge bg-muted-fill p-3">
          <span className="max-w-prose text-[12.5px] text-g700">
            {`Erase ${app.candidate.name}'s data? This permanently removes all their applications with your company - CV files, assessment results, notes and calendar events. It cannot be undone.`}
          </span>
          <button
            type="button"
            disabled={eraseBusy}
            onClick={() => void confirmErase()}
            className="inline-flex h-7 items-center rounded-sm bg-red-600 px-2.5 text-[12.5px] font-medium text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            {eraseBusy ? "…" : "Yes, erase"}
          </button>
          <button
            type="button"
            disabled={eraseBusy}
            onClick={() => setConfirmingErase(false)}
            className="inline-flex h-7 items-center rounded-sm border border-edge bg-surface px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50"
          >
            Keep
          </button>
        </div>
      ) : null}

      <Dialog open={emailOpen} onOpenChange={setEmailOpen}>
        <DialogContent>
          <DialogTitle>Edit candidate email</DialogTitle>
          <DialogDescription>
            Quiz, status and booking emails go to this address. Existing links keep working.
          </DialogDescription>
          <form onSubmit={(event) => void saveEmail(event)} className="mt-3 space-y-3">
            <div>
              <label
                htmlFor={`candidate-email-${app.id}`}
                className="mb-1 block text-[12.5px] font-medium text-g600"
              >
                Candidate email
              </label>
              <input
                id={`candidate-email-${app.id}`}
                type="email"
                required
                value={emailDraft}
                disabled={emailBusy}
                onChange={(event) => setEmailDraft(event.target.value)}
                className="h-8 w-full rounded-md border border-edge bg-surface px-2.5 text-[13px] outline-none focus:border-accent disabled:opacity-60"
              />
            </div>
            {emailError ? (
              <p role="alert" className="text-[12.5px] text-red-600 dark:text-red-400">
                {emailError}
              </p>
            ) : null}
            <button
              type="submit"
              disabled={emailBusy}
              className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
            >
              {emailBusy ? "…" : "Save email"}
            </button>
          </form>
        </DialogContent>
      </Dialog>
      <MessageDialog
        key={`message-${messageOpening}`}
        open={messageOpen}
        applicationId={app.id}
        candidateName={app.candidate.name}
        onSend={async (fields) => {
          const result = await onSendMessage(fields);
          if (result === null) setMessageOpen(false);
          return result;
        }}
        onCancel={() => setMessageOpen(false)}
      />
      <StageEmailDialog
        key={dialog ? `${dialog.stage}-${dialog.email}` : "closed"}
        open={dialog !== null}
        applicationId={app.id}
        candidateName={app.candidate.name}
        stage={dialog?.stage ?? "rejected"}
        email={dialog?.email ?? false}
        onConfirm={(fields) => {
          const { stage, email } = dialog ?? { stage: "rejected" as const, email: notify };
          setDialog(null);
          onStage(stage, email, fields);
        }}
        onCancel={() => setDialog(null)}
      />

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

      <TimelineCard
        key={`timeline-${app.id}`}
        applicationId={app.id}
        now={now}
        refreshKey={trailTick}
      />
      <AccessTrailCard key={`access-${app.id}`} applicationId={app.id} now={now} />
      <NotesCard key={app.id} applicationId={app.id} />
    </div>
  );
}

function ApplicantsContent() {
  // The URL is the state (card "Applicant list"): every filter, the sort
  // and the open applicant live in the query string so a view can be
  // shared, survives a refresh and works with the back button. Deep links
  // (dashboard queue, emails) name the applicant to open as ?selected=<id>;
  // the list is paginated, so one outside the first page is fetched on its
  // own and pinned to the top.
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [requestedId] = useState(() => searchParams.get("selected"));
  const requestHandled = useRef(false);
  const [filters, setFilters] = useState<ApplicantFilters>(() => parseFilters(searchParams));
  const lastWritten = useRef<string | null>(null);
  const [items, setItems] = useState<ApplicationOut[] | null>(null);
  const [total, setTotal] = useState(0);
  const [stageCounts, setStageCounts] = useState<Partial<Record<ApplicationStage, number>>>({});
  const [sources, setSources] = useState<string[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(requestedId);
  const [checked, setChecked] = useState<Map<string, string>>(new Map());
  const [answersById, setAnswersById] = useState<Record<string, QuizAnswerReview[]>>({});
  const loadingAnswersFor = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // bumps after panel actions that write a timeline row, so the trail refetches
  const [trailTick, setTrailTick] = useState(0);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (notice === null) return;
    const id = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(id);
  }, [notice]);

  // back/forward: a query string we did not write ourselves wins
  useEffect(() => {
    const current = searchParams.toString();
    if (current === lastWritten.current) return;
    lastWritten.current = current;
    setFilters(parseFilters(searchParams));
  }, [searchParams]);

  const writeUrl = useCallback(
    (next: ApplicantFilters, selected: string | null) => {
      const qs = filtersToParams(next, selected ? { selected } : {}).toString();
      lastWritten.current = qs;
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname],
  );

  function updateFilters(change: Partial<ApplicantFilters>) {
    const next = { ...filters, ...change };
    setFilters(next);
    if (change.job !== undefined && change.job !== filters.job) setChecked(new Map());
    // a view change drops ?selected=: the open row is whatever the new
    // list puts first, and a shared link should not carry a stale pin
    writeUrl(next, null);
  }

  function selectApplicant(id: string) {
    setSelectedId(id);
    writeUrl(filters, id);
  }

  // one string is the whole query: the effect below reruns only when the
  // query actually changes, not on every object identity
  const filterKey = filtersToParams(filters).toString();

  const reload = useCallback(() => {
    applications
      .list({
        ...toApiFilters(parseFilters(new URLSearchParams(filterKey))),
        limit: LIST_PAGE_SIZE,
      })
      .then(async (page) => {
        let rows = page.items;
        const firstLoad = !requestHandled.current;
        requestHandled.current = true;
        if (firstLoad && requestedId !== null && !rows.some((row) => row.id === requestedId)) {
          const pinned = await applications.get(requestedId).catch(() => null);
          if (pinned !== null) rows = [pinned, ...rows];
        }
        setItems(rows);
        setTotal(page.total);
        setStageCounts(page.stage_counts);
        setSources(page.sources ?? []);
        setSelectedId((current) => {
          if (current && rows.some((row) => row.id === current)) return current;
          return rows[0]?.id ?? null;
        });
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load applications"),
      );
  }, [filterKey, requestedId]);

  const loadMore = useCallback(() => {
    if (items === null) return;
    setLoadingMore(true);
    applications
      .list({
        ...toApiFilters(parseFilters(new URLSearchParams(filterKey))),
        limit: LIST_PAGE_SIZE,
        offset: items.length,
      })
      .then((page) => {
        setItems((prev) => [...(prev ?? []), ...page.items]);
        setTotal(page.total);
        setStageCounts(page.stage_counts);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load applications"),
      )
      .finally(() => setLoadingMore(false));
  }, [items, filterKey]);

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
    // server-side whole-set counts (M5.7 H4): correct even when only one
    // page of rows is loaded
    const base: Record<StagePill["value"], number> = {
      all: 0,
      new: 0,
      screening: 0,
      interview: 0,
      offer: 0,
      hired: 0,
      rejected: 0,
      withdrawn: 0,
    };
    for (const [stage, count] of Object.entries(stageCounts)) {
      base[stage as ApplicationStage] = count ?? 0;
      base.all += count ?? 0;
    }
    return base;
  }, [stageCounts]);

  async function changeStage(
    id: string,
    stage: ApplicationStage,
    notify: boolean,
    fields?: StageFields,
  ) {
    setError(null);
    const before = items?.find((row) => row.id === id) ?? null;
    try {
      // the reason only exists on a rejection; immediate moves send none
      await (fields
        ? applications.setStage(id, stage, notify, fields)
        : applications.setStage(id, stage, notify));
      setTrailTick((tick) => tick + 1);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stage change failed");
      return;
    }
    if (before === null || before.stage === stage) return;
    const previous = before.stage;
    const name = before.candidate.name;
    // an email that went out cannot be unsent; the toast says so and
    // undo moves the row back quietly
    setToast({
      id: Date.now(),
      text: `Moved ${name} to ${STAGE_LABELS[stage]}.${notify ? " Email sent." : ""}`,
      action: {
        label: "Undo",
        run: async () => {
          setToast(null);
          try {
            await applications.setStage(id, previous, false);
            setTrailTick((tick) => tick + 1);
            reload();
            setToast({ id: Date.now(), text: `Moved ${name} back to ${STAGE_LABELS[previous]}.` });
          } catch (err) {
            setError(err instanceof Error ? err.message : "Undo failed");
          }
        },
      },
    });
  }

  async function remindCandidate(id: string): Promise<boolean> {
    setError(null);
    try {
      await applications.remind(id);
      setTrailTick((tick) => tick + 1);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reminder failed");
      return false;
    }
  }

  async function sendMessage(id: string, fields: MessageInput): Promise<string | null> {
    try {
      await applications.sendMessage(id, fields);
    } catch (err) {
      return err instanceof Error ? err.message : "Message failed";
    }
    setTrailTick((tick) => tick + 1);
    setToast({ id: Date.now(), text: "Message sent." });
    return null;
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

  async function downloadDsar(app: ApplicationOut) {
    setError(null);
    try {
      const bundle = await applications.dsarExport(app.id);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `dsar-${app.candidate.email.replace(/[^a-z0-9.@_-]/gi, "_")}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    }
  }

  async function eraseCandidate(id: string): Promise<boolean> {
    setError(null);
    try {
      const result = await applications.eraseCandidate(id);
      setNotice(
        result.google_event_failures > 0
          ? `Candidate data erased - ${result.google_event_failures} calendar event(s) could not be removed`
          : "Candidate data erased",
      );
      setChecked(new Map());
      reload();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erase failed");
      return false;
    }
  }

  async function updateCandidateEmail(id: string, email: string): Promise<string | null> {
    try {
      await applications.updateCandidateEmail(id, email);
      reload();
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : "Email update failed";
    }
  }

  const selected = items?.find((app) => app.id === selectedId) ?? null;

  function toggleChecked(id: string, name: string, isChecked: boolean) {
    setChecked((current) => {
      const next = new Map(current);
      if (isChecked) next.set(id, name);
      else next.delete(id);
      return next;
    });
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Applicants</h1>
        <div className="flex items-center gap-2">
          {(["csv", "json"] as const).map((format) => (
            <a
              key={format}
              href={applications.exportUrl(format, toApiFilters(filters))}
              download
              className="inline-flex h-[34px] items-center gap-1.5 rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill"
            >
              <Download aria-hidden className="h-3.5 w-3.5" />
              Export {format.toUpperCase()}
            </a>
          ))}
        <div className="relative">
          <select
            aria-label="Filter by job"
            value={filters.job}
            onChange={(event) => updateFilters({ job: event.target.value })}
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
      </div>

      <div className="flex flex-wrap gap-1.5">
        {STAGE_PILLS.map((pill) => (
          <button
            key={pill.value}
            type="button"
            aria-pressed={filters.stage === pill.value}
            onClick={() => updateFilters({ stage: pill.value })}
            className={`inline-flex h-7 items-center rounded-full px-[11px] text-[12.5px] font-medium ${
              filters.stage === pill.value
                ? "bg-inverse text-inverse-foreground"
                : "border border-edge bg-surface text-g700 hover:border-g400"
            }`}
          >
            {pill.label} · {counts[pill.value]}
          </button>
        ))}
      </div>

      <ApplicantFilterBar filters={filters} sources={sources} onChange={updateFilters} />

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p
          role="status"
          className="text-sm font-medium text-emerald-700 dark:text-emerald-400"
        >
          {notice}
        </p>
      ) : null}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[360px_1fr]">
        {/* overflow-clip, not overflow-hidden: hidden would make this card the
            sticky containing block and the bulk bar would never pin to the
            viewport; clip rounds the corners the same way */}
        <div className="card overflow-clip">
          <div className="flex items-center gap-3 border-b border-divider py-1.5 pr-2 pl-4">
            <input
              type="checkbox"
              aria-label="Select all on this page"
              disabled={!items || items.length === 0}
              checked={!!items && items.length > 0 && items.every((app) => checked.has(app.id))}
              ref={(el) => {
                if (el) el.indeterminate = checked.size > 0 && !!items && !items.every((app) => checked.has(app.id));
              }}
              onChange={(event) => {
                if (!items) return;
                if (event.target.checked) {
                  setChecked(new Map(items.map((app) => [app.id, app.candidate.name])));
                } else {
                  setChecked(new Map());
                }
              }}
              className="h-[15px] w-[15px] shrink-0 cursor-pointer accent-[var(--color-accent)] disabled:cursor-default"
            />
            <span className="font-mono text-[11px] text-g500" aria-live="polite">
              {items === null
                ? "…"
                : countActive(filters) > 0
                  ? `${total} match`
                  : `${total} applicant${total === 1 ? "" : "s"}`}
            </span>
            <div className="relative ml-auto">
              <select
                aria-label="Sort applicants"
                value={filters.sort}
                onChange={(event) => updateFilters({ sort: event.target.value as SortKey })}
                className="h-7 appearance-none rounded-md border border-transparent bg-transparent pr-6 pl-2 text-[12px] text-g600 outline-none hover:border-edge focus:border-g400"
              >
                {SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <ChevronDown
                aria-hidden
                className="pointer-events-none absolute top-1/2 right-1.5 h-3.5 w-3.5 -translate-y-1/2 text-g500"
              />
            </div>
          </div>
          {items === null ? (
            <div aria-busy="true" className="p-3">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="mb-2 h-14 animate-pulse rounded-sm bg-muted-fill" />
              ))}
            </div>
          ) : items.length === 0 ? (
            countActive(filters) > 0 ? (
              <div className="flex flex-col items-start gap-2 p-4 text-sm text-g500">
                <span>No applicants match these filters.</span>
                <button
                  type="button"
                  onClick={() => updateFilters(clearNarrowing(filters))}
                  className="inline-flex h-7 items-center rounded-md border border-edge bg-surface px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
                >
                  Clear filters
                </button>
              </div>
            ) : (
              <p className="p-4 text-sm text-g500">No applications match.</p>
            )
          ) : (
            <ul>
              {items.map((app) => {
                const isSelected = selectedId === app.id;
                const hasFlags = (app.quiz_attempt?.integrity.flags?.length ?? 0) > 0;
                return (
                  <li
                    key={app.id}
                    className={`flex items-center gap-3 border-t border-divider first:border-t-0 ${
                      isSelected
                        ? "border-l-[3px] border-l-accent bg-accent/[0.06]"
                        : "border-l-[3px] border-l-transparent hover:bg-hover-fill"
                    }`}
                  >
                    {/* sibling of the row button - a checkbox nested inside a
                        button is invalid and unreachable for AT (H5 ledger) */}
                    <input
                      type="checkbox"
                      aria-label={`Select ${app.candidate.name}`}
                      checked={checked.has(app.id)}
                      onChange={(event) =>
                        toggleChecked(app.id, app.candidate.name, event.target.checked)
                      }
                      className="ml-4 h-[15px] w-[15px] shrink-0 cursor-pointer accent-[var(--color-accent)]"
                    />
                    <button
                      type="button"
                      onClick={() => selectApplicant(app.id)}
                      aria-current={isSelected ? "true" : undefined}
                      className="flex min-w-0 flex-1 items-center gap-3 py-[13px] pr-4 text-left"
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
                        {filters.job === "" ? (
                          <p className="mt-0.5 truncate text-[11.5px] text-g600">
                            {jobLookup[app.job_id] ?? "-"}
                          </p>
                        ) : null}
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
          {items !== null && items.length < total ? (
            <div className="border-t border-divider p-2.5 text-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="inline-flex h-8 items-center rounded-md px-3 text-[12.5px] font-medium text-g600 hover:bg-hover-fill disabled:opacity-50"
              >
                {loadingMore ? "…" : `Load more (${items.length} of ${total})`}
              </button>
            </div>
          ) : null}
          <BulkActionBar
            selected={checked}
            onClear={() => setChecked(new Map())}
            onChanged={() => {
              setChecked(new Map());
              reload();
            }}
          />
        </div>

        {selected ? (
          <DetailPanel
            key={selected.id}
            app={selected}
            jobTitle={jobLookup[selected.job_id] ?? "-"}
            answers={answersById[selected.id] ?? null}
            onStage={(stage, notify, fields) => changeStage(selected.id, stage, notify, fields)}
            onDownloadCv={() => downloadCv(selected.id)}
            onRemind={() => remindCandidate(selected.id)}
            onExport={() => void downloadDsar(selected)}
            onErase={() => eraseCandidate(selected.id)}
            onUpdateEmail={(email) => updateCandidateEmail(selected.id, email)}
            onSendMessage={(fields) => sendMessage(selected.id, fields)}
            now={now}
            trailTick={trailTick}
          />
        ) : items === null ? (
          <div className="card h-[540px] animate-pulse" />
        ) : (
          <div className="card flex h-[540px] items-center justify-center p-6 text-sm text-g500">
            Select an applicant to review.
          </div>
        )}
      </div>
      <Toast message={toast} onDismiss={() => setToast(null)} />
    </section>
  );
}

export default function ApplicantsPage() {
  return (
    <Suspense>
      <ApplicantsContent />
    </Suspense>
  );
}
