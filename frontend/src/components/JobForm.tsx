"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Bold, ExternalLink, Heading2, Italic, Link2, List, X } from "lucide-react";

import { questionnaires, questions } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import type {
  Difficulty,
  EmploymentType,
  JobInput,
  JobOut,
  QuestionnaireOut,
  QuizConfig,
  RemotePolicy,
  SalaryPeriod,
} from "@/lib/api";

/** Job form, handoff screen 08: two-column layout with a fields card and a
 * right rail holding the Skills assessment card (toggle, difficulty chips,
 * segmented per-question timer). Questionnaire attach lands with D4. */

const DIFFICULTIES: Difficulty[] = [1, 2, 3, 4, 5];
const TIMER_PRESETS = [20, 25, 30];

const REMOTE_POLICIES: { value: RemotePolicy; label: string }[] = [
  { value: "onsite", label: "On-site" },
  { value: "hybrid", label: "Hybrid" },
  { value: "remote", label: "Remote" },
];

const EMPLOYMENT_TYPES: { value: EmploymentType; label: string }[] = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
];

const SALARY_PERIODS: { value: SalaryPeriod; label: string }[] = [
  { value: "year", label: "per year" },
  { value: "month", label: "per month" },
  { value: "week", label: "per week" },
  { value: "day", label: "per day" },
  { value: "hour", label: "per hour" },
];

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm outline-none focus:border-g400";
const labelCls = "text-[13.5px] font-medium";

function ToolbarButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded-[7px] text-g700 hover:bg-divider"
    >
      {children}
    </button>
  );
}

export function JobForm({
  initial,
  submitLabel,
  onSubmit,
  rail,
}: {
  initial?: JobOut;
  submitLabel: string;
  onSubmit: (values: JobInput) => Promise<void>;
  /** Extra right-rail content (e.g. the Status card on the edit page). */
  rail?: React.ReactNode;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tags, setTags] = useState<string[]>(initial?.tags ?? []);
  const [tagDraft, setTagDraft] = useState("");
  const [quizEnabled, setQuizEnabled] = useState(initial?.quiz_config.enabled ?? false);
  const [difficulties, setDifficulties] = useState<Difficulty[]>(
    initial?.quiz_config.difficulties ?? [],
  );
  const [timeLimit, setTimeLimit] = useState<number | null>(
    initial ? initial.quiz_config.time_limit_seconds : 20,
  );
  const [questionnaireId, setQuestionnaireId] = useState<string | null>(
    initial?.quiz_config.questionnaire_id ?? null,
  );
  const [availableQuestionnaires, setAvailableQuestionnaires] = useState<
    QuestionnaireOut[] | null
  >(null);
  const [mixCache, setMixCache] = useState<
    Record<string, { easy: number; medium: number; hard: number; total: number; seconds: number }>
  >({});
  const descriptionRef = useRef<HTMLTextAreaElement>(null);

  // Load the list once the assessment section is expanded — populates the picker
  // and lets us look up the attached one by name without another fetch.
  useEffect(() => {
    if (!quizEnabled || availableQuestionnaires !== null) return;
    questionnaires
      .list()
      .then(setAvailableQuestionnaires)
      .catch(() => setAvailableQuestionnaires([]));
  }, [quizEnabled, availableQuestionnaires]);

  // Fetch the difficulty mix for the attached questionnaire once; cache by
  // id so switching between attach targets doesn't re-fetch every time. All
  // state updates live inside the resolve promise handler (lint rule
  // `react-hooks/set-state-in-effect`).
  useEffect(() => {
    if (questionnaireId === null) return;
    if (mixCache[questionnaireId] !== undefined) return;
    const attached = availableQuestionnaires?.find((q) => q.id === questionnaireId);
    if (!attached) return;
    let cancelled = false;
    const refs = attached.question_refs;
    const total = refs.length;
    const fetchMix = total === 0 ? Promise.resolve([]) : questions.resolve(refs);
    fetchMix
      .then((rows) => {
        if (cancelled) return;
        setMixCache((current) => ({
          ...current,
          [questionnaireId]: {
            easy: rows.filter((r) => r.difficulty <= 2).length,
            medium: rows.filter((r) => r.difficulty === 3).length,
            hard: rows.filter((r) => r.difficulty >= 4).length,
            total,
            seconds: rows.reduce((sum, r) => sum + r.time_limit_seconds, 0),
          },
        }));
      })
      .catch(() => {
        // best-effort — the card falls back to the "no mix yet" branch
      });
    return () => {
      cancelled = true;
    };
  }, [questionnaireId, availableQuestionnaires, mixCache]);

  const attachedQuestionnaire =
    questionnaireId === null
      ? null
      : (availableQuestionnaires?.find((q) => q.id === questionnaireId) ?? null);
  const attachedMix = questionnaireId === null ? null : (mixCache[questionnaireId] ?? null);

  const timerOptions: { value: number | null; label: string }[] = TIMER_PRESETS.map(
    (seconds) => ({ value: seconds, label: `${seconds}s` }),
  );
  if (timeLimit === null || !TIMER_PRESETS.includes(timeLimit)) {
    timerOptions.push(
      timeLimit === null
        ? { value: null, label: "per-q" }
        : { value: timeLimit, label: `${timeLimit}s` },
    );
  }

  function addTag(raw: string) {
    const tag = raw.trim().toLowerCase();
    if (tag === "") return;
    setTags((current) => (current.includes(tag) ? current : [...current, tag]));
    setTagDraft("");
  }

  function onTagKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addTag(tagDraft);
    } else if (event.key === "Backspace" && tagDraft === "" && tags.length > 0) {
      setTags((current) => current.slice(0, -1));
    }
  }

  function wrapSelection(before: string, after: string, placeholder: string) {
    const textarea = descriptionRef.current;
    if (!textarea) return;
    const { selectionStart, selectionEnd, value } = textarea;
    const selected = value.slice(selectionStart, selectionEnd) || placeholder;
    const next =
      value.slice(0, selectionStart) + before + selected + after + value.slice(selectionEnd);
    textarea.value = next;
    textarea.focus();
    const cursor = selectionStart + before.length + selected.length;
    textarea.setSelectionRange(selectionStart + before.length, cursor);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const data = new FormData(event.currentTarget);
    const str = (name: string) => String(data.get(name) ?? "").trim();
    const num = (name: string) => (str(name) === "" ? null : Number(str(name)));
    try {
      const quizTags = str("quiz_tags")
        .split(",")
        .map((tag) => tag.trim().toLowerCase())
        .filter(Boolean);
      const quiz_config: QuizConfig = {
        enabled: quizEnabled,
        tags: quizTags.length > 0 ? quizTags : null,
        question_count: Number(str("quiz_question_count") || "6"),
        include_company_questions: true,
        time_limit_seconds: timeLimit,
        difficulties: difficulties.length > 0 ? [...difficulties].sort() : null,
        // excludes are managed from the quiz preview panel; carry them through
        exclude_ids: initial?.quiz_config.exclude_ids ?? [],
        questionnaire_id: questionnaireId,
      };
      await onSubmit({
        title: str("title"),
        description_md: str("description_md"),
        location: str("location"),
        remote_policy: str("remote_policy") as RemotePolicy,
        employment_type: str("employment_type") as EmploymentType,
        salary_min: num("salary_min"),
        salary_max: num("salary_max"),
        salary_currency: str("salary_currency") === "" ? null : str("salary_currency"),
        salary_period: str("salary_period") as SalaryPeriod,
        closes_at: str("closes_at") === "" ? null : str("closes_at"),
        tags,
        quiz_config,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[1fr_340px]"
    >
      <div className="card flex flex-col gap-5 p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Job title</span>
            <input name="title" required defaultValue={initial?.title} className={inputCls} />
          </label>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Location</span>
            <input name="location" defaultValue={initial?.location} className={inputCls} />
          </label>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Remote policy</span>
            <select
              name="remote_policy"
              defaultValue={initial?.remote_policy ?? "onsite"}
              className={inputCls}
            >
              {REMOTE_POLICIES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Employment type</span>
            <select
              name="employment_type"
              defaultValue={initial?.employment_type ?? "full_time"}
              className={inputCls}
            >
              {EMPLOYMENT_TYPES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Salary min</span>
            <input
              name="salary_min"
              type="number"
              min={0}
              defaultValue={initial?.salary_min ?? ""}
              className={inputCls}
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Salary max</span>
            <input
              name="salary_max"
              type="number"
              min={0}
              defaultValue={initial?.salary_max ?? ""}
              className={inputCls}
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Currency (ISO)</span>
            <input
              name="salary_currency"
              maxLength={3}
              placeholder="EUR"
              defaultValue={initial?.salary_currency ?? ""}
              className={inputCls}
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Period</span>
            <select
              name="salary_period"
              defaultValue={initial?.salary_period ?? "year"}
              className={inputCls}
            >
              {SALARY_PERIODS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Closes on</span>
            <input
              name="closes_at"
              type="date"
              defaultValue={initial?.closes_at?.slice(0, 10) ?? ""}
              className={inputCls}
            />
            <span className="text-xs text-g500">
              Optional. Tells search engines when the posting expires — it never
              closes the job for you.
            </span>
          </label>
        </div>

        {initial ? (
          <div className="flex flex-col gap-2">
            <span className={labelCls}>URL slug</span>
            <div className="flex h-9 items-center overflow-hidden rounded-md border border-edge">
              <span className="flex h-full items-center border-r border-edge bg-muted-fill px-3 font-mono text-xs text-g500">
                jobs/
              </span>
              <input
                aria-label="URL slug"
                readOnly
                value={initial.slug}
                className="h-full flex-1 bg-transparent px-3 font-mono text-[12.5px] outline-none"
              />
            </div>
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          <span id="tags-label" className={labelCls}>
            Tags
          </span>
          <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-edge px-2 py-1.5">
            {tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex h-6 items-center gap-1.5 rounded-[7px] bg-muted-fill px-2 font-mono text-[11.5px] text-g700"
              >
                {tag}
                <button
                  type="button"
                  aria-label={`Remove tag ${tag}`}
                  onClick={() => setTags((current) => current.filter((t) => t !== tag))}
                  className="text-g400 hover:text-g700"
                >
                  <X aria-hidden className="h-[11px] w-[11px]" />
                </button>
              </span>
            ))}
            <input
              aria-labelledby="tags-label"
              placeholder="Add tag…"
              value={tagDraft}
              onChange={(event) => setTagDraft(event.target.value)}
              onKeyDown={onTagKeyDown}
              onBlur={() => addTag(tagDraft)}
              className="h-6 min-w-[90px] flex-1 bg-transparent px-1 text-[13px] outline-none"
            />
          </div>
          <span className="text-xs text-g500">
            Shown on the careers page and used for quiz matching.
          </span>
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="description_md" className={labelCls}>
            Description
          </label>
          <div>
            <div className="flex items-center gap-0.5 rounded-t-md border border-edge bg-muted-fill px-2 py-1.5">
              <ToolbarButton label="Bold" onClick={() => wrapSelection("**", "**", "bold")}>
                <Bold aria-hidden className="h-3.5 w-3.5" />
              </ToolbarButton>
              <ToolbarButton label="Italic" onClick={() => wrapSelection("_", "_", "italic")}>
                <Italic aria-hidden className="h-3.5 w-3.5" />
              </ToolbarButton>
              <div aria-hidden className="mx-1 h-[18px] w-px bg-edge" />
              <ToolbarButton label="Heading" onClick={() => wrapSelection("\n## ", "\n", "Heading")}>
                <Heading2 aria-hidden className="h-3.5 w-3.5" />
              </ToolbarButton>
              <ToolbarButton label="Bullet list" onClick={() => wrapSelection("\n- ", "", "item")}>
                <List aria-hidden className="h-3.5 w-3.5" />
              </ToolbarButton>
              <ToolbarButton label="Insert link" onClick={() => wrapSelection("[", "](url)", "text")}>
                <Link2 aria-hidden className="h-3.5 w-3.5" />
              </ToolbarButton>
              <span className="ml-auto font-mono text-[10.5px] text-g400">markdown</span>
            </div>
            <textarea
              id="description_md"
              name="description_md"
              ref={descriptionRef}
              rows={10}
              defaultValue={initial?.description_md}
              className="min-h-[180px] w-full rounded-b-md border border-t-0 border-edge bg-transparent px-4 py-3.5 text-sm leading-[23px] outline-none focus:border-g400"
            />
          </div>
        </div>

        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-4">
        <div className="card px-5 py-[18px]">
          <div className="flex items-center justify-between">
            <span className="font-heading text-[15px] font-semibold">Skills assessment</span>
            <Switch
              checked={quizEnabled}
              aria-label="Skills assessment"
              onCheckedChange={setQuizEnabled}
            />
          </div>
          <p className="mt-1 text-[12.5px] text-g500">
            Sent to candidates right after they apply.
          </p>

          {quizEnabled ? (
            <div className="mt-3.5 flex flex-col gap-3.5">
              {attachedQuestionnaire && attachedMix ? (
                <div className="rounded-md border border-edge p-3.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-semibold">
                      {attachedQuestionnaire.name}
                    </span>
                    <span className="shrink-0 font-mono text-[10.5px] text-g500">
                      {attachedMix.seconds > 0
                        ? `~${Math.max(1, Math.round(attachedMix.seconds / 60))} min`
                        : ""}
                    </span>
                  </div>
                  {attachedMix.total > 0 ? (
                    <>
                      <div className="mt-2 flex h-1.5 overflow-hidden rounded-full">
                        <span
                          className="block bg-emerald-200 dark:bg-emerald-900"
                          style={{ width: `${(attachedMix.easy / attachedMix.total) * 100}%` }}
                        />
                        <span
                          className="block bg-amber-200 dark:bg-amber-900"
                          style={{ width: `${(attachedMix.medium / attachedMix.total) * 100}%` }}
                        />
                        <span
                          className="block bg-red-200 dark:bg-red-900"
                          style={{ width: `${(attachedMix.hard / attachedMix.total) * 100}%` }}
                        />
                      </div>
                      <p className="mt-2 font-mono text-[10.5px] text-g500">
                        {attachedMix.total} questions · {attachedMix.easy} easy ·{" "}
                        {attachedMix.medium} medium · {attachedMix.hard} hard
                      </p>
                    </>
                  ) : (
                    <p className="mt-2 font-mono text-[10.5px] text-amber-700 dark:text-amber-400">
                      empty questionnaire — no quiz will be served until it has questions
                    </p>
                  )}
                  <div className="mt-3 flex gap-1.5">
                    <label
                      htmlFor="questionnaire_picker"
                      className="inline-flex h-7 flex-1 cursor-pointer items-center justify-center rounded-sm border border-edge bg-surface text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
                    >
                      Change
                    </label>
                    <Link
                      href={`/admin/questionnaires/${attachedQuestionnaire.id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex h-7 flex-1 items-center justify-center gap-1 rounded-sm border border-edge bg-surface text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
                    >
                      Preview
                      <ExternalLink aria-hidden className="h-3 w-3" />
                    </Link>
                    <button
                      type="button"
                      onClick={() => setQuestionnaireId(null)}
                      className="inline-flex h-7 items-center rounded-sm px-2.5 text-[12.5px] font-medium text-g500 hover:bg-muted-fill hover:text-red-600 dark:hover:text-red-400"
                    >
                      Detach
                    </button>
                  </div>
                </div>
              ) : null}

              {availableQuestionnaires !== null && availableQuestionnaires.length > 0 ? (
                <label className="flex flex-col gap-2">
                  <span className="text-[12.5px] font-medium text-g700">
                    {attachedQuestionnaire ? "Change questionnaire" : "Use a questionnaire"}
                  </span>
                  <select
                    id="questionnaire_picker"
                    aria-label="Attach questionnaire"
                    value={questionnaireId ?? ""}
                    onChange={(event) =>
                      setQuestionnaireId(event.target.value === "" ? null : event.target.value)
                    }
                    className={inputCls}
                  >
                    <option value="">— tag-auto (default) —</option>
                    {availableQuestionnaires.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.name} ({option.question_refs.length}q)
                      </option>
                    ))}
                  </select>
                </label>
              ) : availableQuestionnaires !== null ? (
                <p className="text-[12.5px] text-g500">
                  No questionnaires yet.{" "}
                  <Link
                    href="/admin/questionnaires"
                    className="text-accent hover:underline"
                  >
                    Build one
                  </Link>{" "}
                  for a curated set of questions.
                </p>
              ) : null}

              {questionnaireId === null ? (
                <>
                  <label className="flex flex-col gap-2">
                    <span className="text-[12.5px] font-medium text-g700">Questions</span>
                    <input
                      name="quiz_question_count"
                      type="number"
                      min={1}
                      max={20}
                      defaultValue={initial?.quiz_config.question_count ?? 6}
                      className={inputCls}
                    />
                  </label>
                  <label className="flex flex-col gap-2">
                    <span className="text-[12.5px] font-medium text-g700">
                      Question tags (defaults to job tags)
                    </span>
                    <input
                      name="quiz_tags"
                      placeholder="python, asyncio"
                      defaultValue={initial?.quiz_config.tags?.join(", ") ?? ""}
                      className={`${inputCls} font-mono text-[12.5px]`}
                    />
                  </label>
                  <div className="flex flex-col gap-2">
                    <span className="text-[12.5px] font-medium text-g700">
                      Difficulty (none = all)
                    </span>
                    <div className="flex gap-1.5">
                      {DIFFICULTIES.map((level) => (
                        <button
                          key={level}
                          type="button"
                          aria-pressed={difficulties.includes(level)}
                          aria-label={`Difficulty ${level}`}
                          onClick={() =>
                            setDifficulties((current) =>
                              current.includes(level)
                                ? current.filter((d) => d !== level)
                                : [...current, level],
                            )
                          }
                          className={`inline-flex h-[30px] flex-1 items-center justify-center rounded-sm font-mono text-xs ${
                            difficulties.includes(level)
                              ? "border-[1.5px] border-accent font-semibold text-accent"
                              : "border border-edge text-g500 hover:border-g400"
                          }`}
                        >
                          {level}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              ) : null}

              <div className="flex flex-col gap-2">
                <span className="text-[12.5px] font-medium text-g700">Time per question</span>
                <div className="flex gap-1.5">
                  {timerOptions.map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      aria-pressed={timeLimit === option.value}
                      onClick={() => setTimeLimit(option.value)}
                      className={`inline-flex h-[30px] flex-1 items-center justify-center rounded-sm font-mono text-xs ${
                        timeLimit === option.value
                          ? "border-[1.5px] border-accent font-semibold text-accent"
                          : "border border-edge text-g500 hover:border-g400"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          <p className="mt-3 text-xs leading-[18px] text-g500">
            Switch off to accept CV-only applications for this role.
          </p>
        </div>

        {rail}

        <button
          type="submit"
          disabled={busy}
          className="inline-flex h-8 items-center justify-center rounded-md bg-inverse px-3 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : submitLabel}
        </button>
      </div>
    </form>
  );
}
