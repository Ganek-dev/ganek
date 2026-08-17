"use client";

import { useCallback, useEffect, useState } from "react";

import { DifficultyDots } from "@/components/DifficultyDots";
import { api, type QuizPreview } from "@/lib/api";

const badgeCls = "rounded-full px-2 py-0.5 text-xs font-medium";

/** Recruiter-side preview of a job's quiz pool with per-job exclude toggles.
 *  Excludes PATCH the job's quiz_config immediately (no form round-trip). */
export function QuizPreviewPanel({ jobId }: { jobId: string }) {
  const [preview, setPreview] = useState<QuizPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showPool, setShowPool] = useState(false);

  const reload = useCallback(() => {
    api.jobs
      .quizPreview(jobId)
      .then(setPreview)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load quiz preview"),
      );
  }, [jobId]);
  useEffect(reload, [reload]);

  async function toggleExclude(questionId: string, currentlyExcluded: boolean) {
    if (!preview) return;
    setError(null);
    setBusyId(questionId);
    try {
      const job = await api.jobs.get(jobId);
      const current = job.quiz_config.exclude_ids ?? [];
      const next = currentlyExcluded
        ? current.filter((id) => id !== questionId)
        : [...current, questionId];
      await api.jobs.update(jobId, { quiz_config: { ...job.quiz_config, exclude_ids: next } });
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update exclusions");
    } finally {
      setBusyId(null);
    }
  }

  if (error) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        {error}
      </p>
    );
  }
  if (!preview) {
    return <div aria-busy="true" className="h-24 animate-pulse rounded-lg bg-muted-fill" />;
  }
  if (!preview.enabled) {
    return (
      <p className="text-sm text-g500">
        Quiz is disabled for this job — enable it above to preview questions.
      </p>
    );
  }

  const sample = new Set(preview.sample_question_ids);
  const sampleQuestions = preview.pool.filter((q) => sample.has(q.id));
  const shown = showPool ? preview.pool : sampleQuestions;

  return (
    <section className="space-y-3 card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-heading text-sm font-semibold">Quiz preview</h2>
          <p className="text-xs text-g500">
            {preview.eligible_count} eligible question{preview.eligible_count === 1 ? "" : "s"}
            {" · "}
            {Object.entries(preview.eligible_by_tag)
              .map(([tag, count]) => `${tag}: ${count}`)
              .join(" · ")}
            {" · "}
            {preview.time_limit_seconds !== null
              ? `${preview.time_limit_seconds}s per question`
              : "per-question time limits"}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowPool((v) => !v)}
            className="rounded-md border border-edge px-2 py-1 text-sm text-g700 hover:bg-muted-fill"
          >
            {showPool ? `Show sample (${sampleQuestions.length})` : `Show pool (${preview.pool.length})`}
          </button>
          <button
            type="button"
            onClick={reload}
            className="rounded-md border border-edge px-2 py-1 text-sm text-g700 hover:bg-muted-fill"
          >
            Redraw sample
          </button>
        </div>
      </div>

      {preview.eligible_count === 0 ? (
        <p className="text-sm text-warn">
          No eligible questions — loosen the difficulty filter, add tags, or un-exclude questions.
        </p>
      ) : null}

      <ol className="space-y-3">
        {shown.map((question) => {
          const inactive = question.excluded || question.blocked;
          return (
            <li
              key={question.id}
              className={`rounded-lg border border-edge p-3 text-sm ${
                inactive ? "opacity-50" : ""
              }`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="font-medium text-strong">{question.prompt_md}</p>
                <div className="flex shrink-0 items-center gap-1.5">
                  {sample.has(question.id) && showPool ? (
                    <span className={`${badgeCls} bg-inverse text-inverse-foreground`}>
                      in sample
                    </span>
                  ) : null}
                  <DifficultyDots level={question.difficulty} />
                  {question.source === "company" ? (
                    <span className={`${badgeCls} bg-accent/10 text-accent`}>
                      yours
                    </span>
                  ) : null}
                  {question.blocked ? (
                    <span className={`${badgeCls} bg-warn-soft text-warn`}>
                      blocked company-wide
                    </span>
                  ) : (
                    <button
                      type="button"
                      disabled={busyId === question.id}
                      onClick={() => toggleExclude(question.id, question.excluded)}
                      className="rounded-md border border-edge px-2 py-0.5 text-xs text-g700 hover:bg-muted-fill disabled:opacity-50"
                    >
                      {question.excluded ? "Include" : "Exclude"}
                    </button>
                  )}
                </div>
              </div>
              <ul className="mt-1.5 grid grid-cols-1 gap-1 sm:grid-cols-2">
                {Object.entries(question.options).map(([key, text]) => (
                  <li
                    key={key}
                    className={
                      key === question.correct_key
                        ? "text-ok"
                        : "text-g600"
                    }
                  >
                    {`${key === question.correct_key ? "✓" : "·"} ${key}) ${text}`}
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-g400">{question.tags.join(" · ")}</p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
