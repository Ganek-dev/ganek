"use client";

import { useState } from "react";

/** The decision date this candidate's status page promises (card: candidate
 * promises). Empty = the Hiring settings window (applied + N days); a date
 * here wins for this one application. Dates are plain YYYY-MM-DD days. */

function dayOf(iso: string): string {
  return iso.slice(0, 10);
}

function formatDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function DecisionDateControl({
  value,
  appliedAt,
  onSave,
}: {
  /** The team's own date for this application, or null for the settings window. */
  value: string | null;
  /** The application's created_at: the earliest date allowed. */
  appliedAt: string;
  /** Resolves to an error message to show, or null on success. */
  onSave: (date: string | null) => Promise<string | null>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const minDay = dayOf(appliedAt);

  async function save(next: string | null) {
    setBusy(true);
    setError(null);
    const failure = await onSave(next);
    setBusy(false);
    if (failure !== null) setError(failure);
    else setEditing(false);
  }

  return (
    <div className="mt-4 rounded-md border border-divider px-3 py-2.5 text-[13px] text-g600">
      {editing ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft === "") {
              setError("Pick a date, or use the settings default.");
              return;
            }
            if (draft < minDay) {
              setError("The decision date cannot be before the application date.");
              return;
            }
            void save(draft);
          }}
        >
          <label htmlFor="decision-date" className="font-medium text-g700">
            Decision expected by
          </label>
          <input
            id="decision-date"
            type="date"
            min={minDay}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="h-8 rounded-md border border-edge bg-surface px-2 font-mono text-[12.5px] outline-none focus:border-g400"
          />
          <button
            type="submit"
            disabled={busy}
            className="inline-flex h-8 items-center rounded-md bg-accent px-3 text-[12.5px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            {busy ? "…" : "Save"}
          </button>
          {value !== null ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void save(null)}
              className="inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[12.5px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50"
            >
              Use the settings default
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setEditing(false);
              setError(null);
              setDraft(value ?? "");
            }}
            className="text-[12.5px] font-medium text-g500 hover:underline"
          >
            Cancel
          </button>
        </form>
      ) : (
        <p>
          <span className="font-medium text-g700">Decision date shown to the candidate:</span>{" "}
          {value !== null ? formatDay(value) : "the Hiring settings default"}
          {" · "}
          <button
            type="button"
            onClick={() => {
              setDraft(value ?? "");
              setEditing(true);
            }}
            className="font-medium text-accent hover:underline"
          >
            Change
          </button>
        </p>
      )}
      {error ? (
        <p role="alert" className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}
