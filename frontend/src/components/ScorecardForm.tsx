"use client";

import { useId, useState } from "react";

import {
  RECOMMENDATION_LABELS,
  type Recommendation,
  type Scorecard,
  type ScorecardCriterion,
} from "@/lib/api";

/** The scorecard form: one rating row per criterion (four cells plus "Not
 * assessed"), a recommendation and a comment. Shared by the candidate panel
 * and the reviewer page, so it knows nothing about who is filling it in. A
 * failed submit keeps everything the user typed and shows the error inline. */

const RECOMMENDATIONS: Recommendation[] = ["strong_no", "no", "yes", "strong_yes"];
const CELLS = [1, 2, 3, 4];

export interface ScorecardFormBody {
  ratings: Record<string, number>;
  recommendation: Recommendation;
  comment: string | null;
}

export function ScorecardForm({
  criteria,
  initial,
  onSubmit,
  onDecline,
  submitLabel,
}: {
  criteria: ScorecardCriterion[];
  initial?: Pick<Scorecard, "ratings" | "recommendation" | "comment">;
  onSubmit: (body: ScorecardFormBody) => Promise<void>;
  onDecline?: () => Promise<void>;
  submitLabel: string;
}) {
  const uid = useId();
  const [ratings, setRatings] = useState<Record<string, number>>(initial?.ratings ?? {});
  const [recommendation, setRecommendation] = useState<Recommendation | null>(
    initial?.recommendation ?? null,
  );
  const [comment, setComment] = useState(initial?.comment ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<void>, fallback: string) {
    setError(null);
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  function setRating(criterionId: string, value: number | null) {
    setRatings((prev) => {
      const next = { ...prev };
      if (value === null) delete next[criterionId];
      else next[criterionId] = value;
      return next;
    });
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (recommendation === null || busy) return;
        const picked = recommendation;
        const trimmed = comment.trim();
        void run(
          () =>
            onSubmit({
              ratings,
              recommendation: picked,
              comment: trimmed === "" ? null : trimmed,
            }),
          "Failed to save scorecard",
        );
      }}
    >
      {criteria.map((criterion) => {
        const name = `${uid}-${criterion.id}`;
        const current = ratings[criterion.id];
        return (
          <div key={criterion.id}>
            <p id={`${name}-label`} className="text-[13px] font-medium">
              {criterion.label}
            </p>
            {criterion.hint ? <p className="text-[11.5px] text-g500">{criterion.hint}</p> : null}
            <div
              role="radiogroup"
              aria-labelledby={`${name}-label`}
              className="mt-1.5 flex flex-wrap items-center gap-1.5"
            >
              {CELLS.map((value) => (
                <label
                  key={value}
                  className={`inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border font-mono text-[12.5px] has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent ${
                    current === value
                      ? "border-inverse bg-inverse text-inverse-foreground"
                      : "border-edge bg-surface text-g600 hover:bg-muted-fill"
                  }`}
                >
                  <input
                    type="radio"
                    name={name}
                    aria-label={`${value} of 4`}
                    checked={current === value}
                    onChange={() => setRating(criterion.id, value)}
                    className="sr-only"
                  />
                  {value}
                </label>
              ))}
              <label className="ml-1 inline-flex cursor-pointer items-center gap-1.5 text-[12px] text-g500">
                <input
                  type="radio"
                  name={name}
                  checked={current === undefined}
                  onChange={() => setRating(criterion.id, null)}
                />
                Not assessed
              </label>
            </div>
          </div>
        );
      })}

      <div>
        <p className="text-[13px] font-medium">Recommendation</p>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {RECOMMENDATIONS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={recommendation === value}
              onClick={() => setRecommendation(value)}
              className={`inline-flex h-8 items-center rounded-md border px-3 text-[12.5px] font-medium ${
                recommendation === value
                  ? "border-inverse bg-inverse text-inverse-foreground"
                  : "border-edge bg-surface text-g600 hover:bg-muted-fill"
              }`}
            >
              {RECOMMENDATION_LABELS[value]}
            </button>
          ))}
        </div>
      </div>

      <textarea
        aria-label="Comment"
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        rows={3}
        placeholder="Comment (optional)"
        className="w-full rounded-md border border-edge bg-surface px-2.5 py-2 text-[13px] outline-none focus:border-accent"
      />

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy || recommendation === null}
          className="inline-flex h-8 items-center rounded-md bg-inverse px-3 text-[12.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {submitLabel}
        </button>
        {onDecline ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(onDecline, "Failed to decline")}
            className="text-[12px] text-g500 hover:underline disabled:opacity-50"
          >
            I did not assess this candidate
          </button>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </form>
  );
}
