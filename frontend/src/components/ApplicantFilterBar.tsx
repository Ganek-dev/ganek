"use client";

import { useEffect, useState } from "react";

import { ChevronDown, Search, X } from "lucide-react";

import {
  clearNarrowing,
  countActive,
  DEFAULT_FILTERS,
  type ApplicantFilters,
} from "@/lib/applicant-filters";

/** One filter bar under the stage pills (card "Applicant list"): search,
 * then pick lists for score, quiz state, source, flags and date, then
 * "Clear filters" once anything narrows the set. Presets over free
 * ranges: one click each, and the URL stays generic (`score=60`) so any
 * value works when typed. Native selects on purpose: the admin's other
 * filters (job, access log) already are, they reopen on click and read
 * well to assistive tech without extra wiring. */

const SEARCH_DEBOUNCE_MS = 250;

const SCORE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "Any score" },
  { value: "80", label: "80% and above" },
  { value: "60", label: "60% and above" },
  { value: "40", label: "40% and above" },
];

const QUIZ_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "Any quiz state" },
  { value: "completed", label: "Completed" },
  { value: "pending", label: "Not started" },
  { value: "in_progress", label: "In progress" },
  { value: "expired", label: "Expired" },
  { value: "none", label: "No quiz" },
];

const FLAG_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "Any flags" },
  { value: "true", label: "Flagged" },
  { value: "false", label: "No flags" },
];

const DAYS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "Any time" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const selectCls =
  "h-8 appearance-none rounded-md border border-edge bg-surface pr-7 pl-2.5 text-[12.5px] text-g700 outline-none focus:border-g400 disabled:opacity-50";

function FilterSelect({
  label,
  value,
  options,
  onChange,
  disabled,
  active,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  disabled?: boolean;
  active: boolean;
}) {
  return (
    <div className="relative">
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={`${selectCls} ${active ? "border-accent/60 font-medium" : ""}`}
      >
        {options.map((option) => (
          <option key={option.value || "any"} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2 h-3.5 w-3.5 -translate-y-1/2 text-g500"
      />
    </div>
  );
}

function sourceLabel(source: string): string {
  return source === "direct" ? "Direct" : source;
}

export function ApplicantFilterBar({
  filters,
  sources,
  onChange,
  disabled = false,
}: {
  filters: ApplicantFilters;
  sources: string[];
  onChange: (change: Partial<ApplicantFilters>) => void;
  disabled?: boolean;
}) {
  // Typing leads, the URL follows after the debounce; a change that arrives
  // from the URL itself (clear, back button) wins. `committed` is the last
  // value both sides agreed on, so an echo of our own change never clobbers
  // keystrokes typed in the meantime.
  const [committed, setCommitted] = useState(filters.q);
  const [draft, setDraft] = useState(filters.q);
  if (filters.q !== committed) {
    setCommitted(filters.q);
    setDraft(filters.q);
  }

  useEffect(() => {
    if (draft === committed) return;
    const id = setTimeout(() => {
      setCommitted(draft);
      onChange({ q: draft });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [draft, committed, onChange]);

  const active = countActive(filters);
  const sourceOptions = [
    { value: "", label: "Any source" },
    ...sources.map((source) => ({ value: source, label: sourceLabel(source) })),
  ];
  // a source from a shared link that this company has not seen stays selectable
  if (filters.source !== null && !sources.includes(filters.source)) {
    sourceOptions.push({ value: filters.source, label: sourceLabel(filters.source) });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-g400"
        />
        <input
          type="search"
          aria-label="Search applicants"
          placeholder="Search name or email…"
          value={draft}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          className="h-8 w-56 rounded-md border border-edge bg-surface pr-2.5 pl-8 text-[13px] outline-none placeholder:text-g400 focus:border-g400 disabled:opacity-50"
        />
      </div>
      <FilterSelect
        label="Score"
        value={filters.score === null ? "" : String(filters.score)}
        options={
          filters.score !== null && !SCORE_OPTIONS.some((o) => o.value === String(filters.score))
            ? [...SCORE_OPTIONS, { value: String(filters.score), label: `${filters.score}% and above` }]
            : SCORE_OPTIONS
        }
        active={filters.score !== null}
        disabled={disabled}
        onChange={(value) => onChange({ score: value === "" ? null : Number(value) })}
      />
      <FilterSelect
        label="Quiz"
        value={filters.quiz ?? ""}
        options={QUIZ_OPTIONS}
        active={filters.quiz !== null}
        disabled={disabled}
        onChange={(value) =>
          onChange({ quiz: value === "" ? null : (value as ApplicantFilters["quiz"]) })
        }
      />
      <FilterSelect
        label="Source"
        value={filters.source ?? ""}
        options={sourceOptions}
        active={filters.source !== null}
        disabled={disabled}
        onChange={(value) => onChange({ source: value === "" ? null : value })}
      />
      <FilterSelect
        label="Flags"
        value={filters.flagged === null ? "" : String(filters.flagged)}
        options={FLAG_OPTIONS}
        active={filters.flagged !== null}
        disabled={disabled}
        onChange={(value) => onChange({ flagged: value === "" ? null : value === "true" })}
      />
      <FilterSelect
        label="Applied"
        value={filters.days === null ? "" : String(filters.days)}
        options={
          filters.days !== null && !DAYS_OPTIONS.some((o) => o.value === String(filters.days))
            ? [...DAYS_OPTIONS, { value: String(filters.days), label: `Last ${filters.days} days` }]
            : DAYS_OPTIONS
        }
        active={filters.days !== null}
        disabled={disabled}
        onChange={(value) => onChange({ days: value === "" ? null : Number(value) })}
      />
      {active > 0 ? (
        <button
          type="button"
          onClick={() => {
            const cleared = clearNarrowing(filters);
            onChange({
              q: cleared.q,
              score: cleared.score,
              quiz: cleared.quiz,
              source: cleared.source,
              flagged: cleared.flagged,
              days: cleared.days,
            });
          }}
          className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-[12.5px] font-medium text-g600 hover:bg-hover-fill"
        >
          <X aria-hidden className="h-3.5 w-3.5" />
          Clear filters
        </button>
      ) : null}
    </div>
  );
}

export { DEFAULT_FILTERS };
