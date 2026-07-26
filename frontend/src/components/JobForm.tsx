"use client";

import { useRef, useState } from "react";

import { Bold, Heading2, Italic, Link2, List, X } from "lucide-react";

import type {
  Difficulty,
  EmploymentType,
  JobInput,
  JobOut,
  QuizConfig,
  RemotePolicy,
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
  const descriptionRef = useRef<HTMLTextAreaElement>(null);

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
        // excludes and questionnaire attach are managed elsewhere; carry them through
        exclude_ids: initial?.quiz_config.exclude_ids ?? [],
        questionnaire_id: initial?.quiz_config.questionnaire_id ?? null,
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

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
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
            <button
              type="button"
              role="switch"
              aria-checked={quizEnabled}
              aria-label="Skills assessment"
              onClick={() => setQuizEnabled((on) => !on)}
              className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                quizEnabled ? "bg-accent" : "bg-muted-fill border border-edge"
              }`}
            >
              <span
                aria-hidden
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow-sm transition-all ${
                  quizEnabled ? "right-0.5" : "left-0.5"
                }`}
              />
            </button>
          </div>
          <p className="mt-1 text-[12.5px] text-g500">
            Sent to candidates right after they apply.
          </p>

          {quizEnabled ? (
            <div className="mt-3.5 flex flex-col gap-3.5">
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
