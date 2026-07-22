"use client";

import { useCallback, useEffect, useState } from "react";

import { questions, type Difficulty, type QuestionOut } from "@/lib/api";

const inputCls =
  "w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
const labelCls = "text-sm font-medium text-zinc-700 dark:text-zinc-300";
const OPTION_KEYS = ["a", "b", "c", "d"] as const;

export default function QuestionsPage() {
  const [items, setItems] = useState<QuestionOut[] | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    questions
      .list()
      .then(setItems)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load questions"),
      );
  }, []);
  useEffect(reload, [reload]);

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const data = new FormData(event.currentTarget);
    const str = (name: string) => String(data.get(name) ?? "").trim();
    try {
      await questions.create({
        prompt_md: str("prompt_md"),
        options: {
          a: str("option_a"),
          b: str("option_b"),
          c: str("option_c"),
          d: str("option_d"),
        },
        correct_key: str("correct_key"),
        explanation_md: str("explanation_md"),
        tags: str("tags")
          .split(",")
          .map((tag) => tag.trim().toLowerCase())
          .filter(Boolean),
        difficulty: str("difficulty") as Difficulty,
        time_limit_seconds: Number(str("time_limit_seconds") || "15"),
      });
      setShowForm(false);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create question");
    } finally {
      setBusy(false);
    }
  }

  async function retire(id: string) {
    setError(null);
    try {
      await questions.retire(id);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retire question");
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            Company questions
          </h1>
          <p className="text-sm text-zinc-500">
            Private to your company; mixed into quizzes whose tags match. The open-source
            bank covers general topics — add questions about your stack and domain here.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {showForm ? "Cancel" : "New question"}
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {showForm ? (
        <form
          onSubmit={handleCreate}
          className="space-y-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <label className="block space-y-1">
            <span className={labelCls}>Question (markdown, answerable in ~15s)</span>
            <textarea name="prompt_md" required minLength={10} rows={2} className={inputCls} />
          </label>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {OPTION_KEYS.map((key) => (
              <label key={key} className="block space-y-1">
                <span className={labelCls}>Option {key.toUpperCase()}</span>
                <input name={`option_${key}`} required className={inputCls} />
              </label>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <label className="block space-y-1">
              <span className={labelCls}>Correct</span>
              <select name="correct_key" className={inputCls} defaultValue="a">
                {OPTION_KEYS.map((key) => (
                  <option key={key} value={key}>
                    {key.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className={labelCls}>Difficulty</span>
              <select name="difficulty" className={inputCls} defaultValue="medium">
                <option value="easy">easy</option>
                <option value="medium">medium</option>
                <option value="hard">hard</option>
              </select>
            </label>
            <label className="block space-y-1">
              <span className={labelCls}>Seconds</span>
              <input
                name="time_limit_seconds"
                type="number"
                min={10}
                max={60}
                defaultValue={15}
                className={inputCls}
              />
            </label>
            <label className="block space-y-1">
              <span className={labelCls}>Tags</span>
              <input name="tags" required placeholder="python, internal" className={inputCls} />
            </label>
          </div>
          <label className="block space-y-1">
            <span className={labelCls}>Explanation (shown to reviewers)</span>
            <textarea name="explanation_md" rows={2} className={inputCls} />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {busy ? "…" : "Create question"}
          </button>
        </form>
      ) : null}

      {items === null ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-zinc-500">No company questions yet.</p>
      ) : (
        <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
          {items.map((question) => (
            <li key={question.id} className="flex items-center justify-between gap-4 p-4">
              <div className="min-w-0">
                <p className="truncate font-medium text-zinc-900 dark:text-zinc-50">
                  {question.prompt_md}
                </p>
                <p className="text-sm text-zinc-500">
                  {[question.difficulty, `${question.time_limit_seconds}s`, ...question.tags].join(
                    " · ",
                  )}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {question.status === "retired" ? (
                  <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                    retired
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => retire(question.id)}
                    className="rounded-md border border-zinc-300 px-2 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    Retire
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
