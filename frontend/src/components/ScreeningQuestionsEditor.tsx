"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import type { ScreeningQuestion, ScreeningQuestionType } from "@/lib/api";

/** Editor for a list of screening questions (board card "Per-job screening
 * questions"), shared by the job editor and the Hiring settings' company
 * default set. Controlled: every change goes up through `onChange`; the
 * server validates again on save. A preferred answer only produces a mark
 * for the recruiter; nothing here can reject anyone, and the copy says so. */

export const MAX_QUESTIONS = 20;
export const ACK_HELP =
  "For confirmations the company needs. Not for consent to data processing: the privacy notice covers that.";

const TYPE_LABELS: Record<ScreeningQuestionType, string> = {
  yes_no: "Yes / No",
  single_choice: "Single choice",
  short_text: "Short text",
  acknowledgment: "Acknowledgment",
};

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm text-foreground focus:border-accent focus:outline-none";
const selectCls =
  "h-9 rounded-md border border-edge bg-surface px-2.5 text-sm text-foreground focus:border-accent focus:outline-none";
const iconBtnCls =
  "inline-flex h-7 w-7 items-center justify-center rounded-md text-g500 hover:bg-hover-fill hover:text-foreground disabled:opacity-40";

function localId(): string {
  const bytes = new Uint8Array(4);
  crypto.getRandomValues(bytes);
  return "sq_" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function newLocalQuestion(type: ScreeningQuestionType): ScreeningQuestion {
  return {
    id: localId(),
    type,
    prompt: "",
    options: type === "single_choice" ? ["", ""] : null,
    preferred: null,
    required: type === "acknowledgment",
  };
}

/** The same question re-typed: options and the preferred answer only make
 * sense for their own type, so a switch clears them. */
function retype(question: ScreeningQuestion, type: ScreeningQuestionType): ScreeningQuestion {
  return {
    ...question,
    type,
    options: type === "single_choice" ? ["", ""] : null,
    preferred: null,
    required: type === "acknowledgment" ? true : question.required,
  };
}

export function ScreeningQuestionsEditor({
  value,
  onChange,
  onReset,
}: {
  value: ScreeningQuestion[];
  onChange: (next: ScreeningQuestion[]) => void;
  /** "Reset to company defaults"; rendered only when given. */
  onReset?: () => void;
}) {
  function update(index: number, patch: Partial<ScreeningQuestion>) {
    onChange(value.map((q, i) => (i === index ? { ...q, ...patch } : q)));
  }
  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= value.length) return;
    const next = [...value];
    [next[index], next[target]] = [next[target]!, next[index]!];
    onChange(next);
  }

  return (
    <div className="flex flex-col gap-3">
      {value.map((question, index) => (
        <fieldset
          key={question.id}
          aria-label={`Question ${index + 1}`}
          className="rounded-md border border-edge p-3.5"
        >
          <div className="flex items-start gap-2">
            <label className="block flex-1 space-y-1.5">
              <span className="text-xs font-medium text-g600">Prompt</span>
              <input
                aria-label="Prompt"
                value={question.prompt}
                maxLength={300}
                onChange={(event) => update(index, { prompt: event.currentTarget.value })}
                className={inputCls}
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-g600">Type</span>
              <select
                aria-label="Type"
                value={question.type}
                onChange={(event) =>
                  onChange(
                    value.map((q, i) =>
                      i === index
                        ? retype(q, event.currentTarget.value as ScreeningQuestionType)
                        : q,
                    ),
                  )
                }
                className={selectCls}
              >
                {(Object.keys(TYPE_LABELS) as ScreeningQuestionType[]).map((type) => (
                  <option key={type} value={type}>
                    {TYPE_LABELS[type]}
                  </option>
                ))}
              </select>
            </label>
            <div className="mt-6 flex items-center gap-0.5">
              <button
                type="button"
                aria-label={`Move question ${index + 1} up`}
                disabled={index === 0}
                onClick={() => move(index, -1)}
                className={iconBtnCls}
              >
                <ArrowUp aria-hidden className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label={`Move question ${index + 1} down`}
                disabled={index === value.length - 1}
                onClick={() => move(index, 1)}
                className={iconBtnCls}
              >
                <ArrowDown aria-hidden className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label={`Remove question ${index + 1}`}
                onClick={() => onChange(value.filter((_, i) => i !== index))}
                className={iconBtnCls}
              >
                <Trash2 aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {question.type === "single_choice" ? (
            <div className="mt-3 flex flex-col gap-2">
              {(question.options ?? []).map((option, optionIndex) => (
                <div key={optionIndex} className="flex items-center gap-2">
                  <input
                    aria-label={`Option ${optionIndex + 1}`}
                    value={option}
                    maxLength={100}
                    onChange={(event) => {
                      const options = [...(question.options ?? [])];
                      options[optionIndex] = event.currentTarget.value;
                      const preferred =
                        question.preferred === option ? event.currentTarget.value : question.preferred;
                      update(index, { options, preferred });
                    }}
                    className={inputCls}
                  />
                  <button
                    type="button"
                    aria-label={`Remove option ${optionIndex + 1}`}
                    disabled={(question.options ?? []).length <= 1}
                    onClick={() => {
                      const options = (question.options ?? []).filter((_, i) => i !== optionIndex);
                      update(index, {
                        options,
                        preferred: options.includes(question.preferred ?? "") ? question.preferred : null,
                      });
                    }}
                    className={iconBtnCls}
                  >
                    <Trash2 aria-hidden className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                disabled={(question.options ?? []).length >= 10}
                onClick={() => update(index, { options: [...(question.options ?? []), ""] })}
                className="inline-flex h-7 w-fit items-center gap-1 rounded-md px-2 text-xs font-medium text-g600 hover:bg-hover-fill disabled:opacity-40"
              >
                <Plus aria-hidden className="h-3 w-3" />
                Add option
              </button>
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2">
            {question.type === "yes_no" || question.type === "single_choice" ? (
              <label className="flex items-center gap-2 text-sm">
                <span className="text-xs font-medium text-g600">Preferred answer</span>
                <select
                  aria-label="Preferred answer"
                  value={question.preferred ?? ""}
                  onChange={(event) =>
                    update(index, { preferred: event.currentTarget.value || null })
                  }
                  className={selectCls}
                >
                  <option value="">None</option>
                  {question.type === "yes_no" ? (
                    <>
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </>
                  ) : (
                    (question.options ?? [])
                      .filter((option) => option.trim() !== "")
                      .map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))
                  )}
                </select>
              </label>
            ) : null}
            {question.type === "acknowledgment" ? (
              <span className="text-xs text-g500">Always required</span>
            ) : (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  aria-label="Required"
                  checked={question.required}
                  onChange={(event) => update(index, { required: event.currentTarget.checked })}
                  className="h-4 w-4 accent-[var(--accent)]"
                />
                <span className="text-xs font-medium text-g600">Required</span>
              </label>
            )}
          </div>
          {question.type === "acknowledgment" ? (
            <p className="mt-2 text-xs leading-[18px] text-g500">{ACK_HELP}</p>
          ) : null}
        </fieldset>
      ))}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={value.length >= MAX_QUESTIONS}
          onClick={() => onChange([...value, newLocalQuestion("yes_no")])}
          className="inline-flex h-8 items-center gap-1 rounded-md border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-hover-fill disabled:opacity-40"
        >
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Add question
        </button>
        {onReset ? (
          <button
            type="button"
            onClick={() => {
              if (value.length === 0 || window.confirm("Replace this job's questions with the company defaults?")) {
                onReset();
              }
            }}
            className="inline-flex h-8 items-center rounded-md px-2.5 text-[12.5px] font-medium text-g600 hover:bg-hover-fill"
          >
            Reset to company defaults
          </button>
        ) : null}
      </div>
      <p className="text-xs leading-[18px] text-g500">
        A preferred answer only marks the applicant for you; it never moves, rejects or emails anyone.
      </p>
    </div>
  );
}
