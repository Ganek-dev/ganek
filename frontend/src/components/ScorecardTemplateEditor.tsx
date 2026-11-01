"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import type { ScorecardCriterion } from "@/lib/api";

/** Editor for a scorecard template (spec 5.1), shared by the job editor and
 * the Hiring settings' company default. Controlled: every change goes up
 * through `onChange`. New rows carry `id: ""` (the server assigns one);
 * saved ids ride along untouched through edits and reorders, because a
 * submitted scorecard's snapshot is matched on them. */

export const MAX_CRITERIA = 20;
export const MAX_LABEL = 120;
export const MAX_HINT = 300;
export const LABEL_REQUIRED = "Label is required";
export const LABEL_TOO_LONG = "Keep labels under 120 characters";

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm text-foreground focus:border-accent focus:outline-none";
const iconBtnCls =
  "inline-flex h-7 w-7 items-center justify-center rounded-md text-g500 hover:bg-hover-fill hover:text-foreground disabled:opacity-40";

/** The server rejects an empty label (422) and stores whitespace as given,
 * so hosts call this before saving and block rather than drop rows. */
export function hasBlankLabel(criteria: ScorecardCriterion[]): boolean {
  return criteria.some((c) => c.label.trim() === "");
}

export function ScorecardTemplateEditor({
  value,
  onChange,
  emptyHint,
  showBlank = false,
}: {
  value: ScorecardCriterion[];
  onChange: (next: ScorecardCriterion[]) => void;
  emptyHint: string;
  /** Mark rows with a blank label; hosts set it after a blocked save. */
  showBlank?: boolean;
}) {
  // index of the row whose last label edit was refused for length
  const [tooLong, setTooLong] = useState<number | null>(null);

  function update(index: number, patch: Partial<ScorecardCriterion>) {
    onChange(value.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }
  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= value.length) return;
    const next = [...value];
    [next[index], next[target]] = [next[target]!, next[index]!];
    setTooLong(null);
    onChange(next);
  }

  return (
    <div className="flex flex-col gap-3">
      {value.length === 0 ? <p className="text-[12.5px] leading-[18px] text-g500">{emptyHint}</p> : null}
      {value.map((criterion, index) => (
        <fieldset
          key={index}
          aria-label={`Criterion ${index + 1}`}
          className="rounded-md border border-edge p-3.5"
        >
          <div className="flex items-start gap-2">
            <div className="flex-1 space-y-2">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-g600">Label</span>
                <input
                  aria-label="Criterion label"
                  aria-invalid={tooLong === index}
                  value={criterion.label}
                  onChange={(event) => {
                    const next = event.currentTarget.value;
                    if (next.length > MAX_LABEL) {
                      setTooLong(index);
                      return;
                    }
                    setTooLong(null);
                    update(index, { label: next });
                  }}
                  className={inputCls}
                />
                {showBlank && criterion.label.trim() === "" ? (
                  <span role="alert" className="block text-xs text-red-600 dark:text-red-400">
                    {LABEL_REQUIRED}
                  </span>
                ) : null}
                {tooLong === index ? (
                  <span role="alert" className="block text-xs text-red-600 dark:text-red-400">
                    {LABEL_TOO_LONG}
                  </span>
                ) : null}
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-g600">Hint (optional)</span>
                <input
                  aria-label="Criterion hint"
                  value={criterion.hint}
                  maxLength={MAX_HINT}
                  onChange={(event) => update(index, { hint: event.currentTarget.value })}
                  className={inputCls}
                />
              </label>
            </div>
            <div className="mt-6 flex items-center gap-0.5">
              <button
                type="button"
                aria-label="Move up"
                disabled={index === 0}
                onClick={() => move(index, -1)}
                className={iconBtnCls}
              >
                <ArrowUp aria-hidden className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label="Move down"
                disabled={index === value.length - 1}
                onClick={() => move(index, 1)}
                className={iconBtnCls}
              >
                <ArrowDown aria-hidden className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label="Remove"
                onClick={() => {
                  setTooLong(null);
                  onChange(value.filter((_, i) => i !== index));
                }}
                className={iconBtnCls}
              >
                <Trash2 aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </fieldset>
      ))}
      <div>
        <button
          type="button"
          disabled={value.length >= MAX_CRITERIA}
          onClick={() => onChange([...value, { id: "", label: "", hint: "" }])}
          className="inline-flex h-8 items-center gap-1 rounded-md border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-hover-fill disabled:opacity-40"
        >
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Add criterion
        </button>
      </div>
    </div>
  );
}
