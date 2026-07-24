"use client";

import { useCallback, useEffect, useState } from "react";

import {
  questions,
  type BankPage,
  type Difficulty,
  type QuestionOut,
} from "@/lib/api";

const inputCls =
  "w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
const labelCls = "text-sm font-medium text-zinc-700 dark:text-zinc-300";
const selectCls =
  "rounded-md border border-zinc-300 px-2 py-1 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
const OPTION_KEYS = ["a", "b", "c", "d"] as const;
const PAGE_SIZE = 25;

const DIFFICULTY_TONES: Record<Difficulty, string> = {
  easy: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  hard: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

function BankBrowser() {
  const [page, setPage] = useState<BankPage | null>(null);
  const [tag, setTag] = useState("");
  const [difficulty, setDifficulty] = useState<Difficulty | "">("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const reload = useCallback(() => {
    questions
      .bank({
        tag: tag || undefined,
        difficulty: difficulty === "" ? undefined : difficulty,
        q: search || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      .then(setPage)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load the question bank"),
      );
  }, [tag, difficulty, search, offset]);
  useEffect(reload, [reload]);

  async function toggleBlock(id: string, blocked: boolean) {
    setError(null);
    setBusyId(id);
    try {
      await (blocked ? questions.unblock(id) : questions.block(id));
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Blocking requires an admin account");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        The open-source bank your quizzes draw from. Blocking a question here removes it from
        every quiz across your company; per-job exclusions live on each job&apos;s quiz preview.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Filter by tag"
          value={tag}
          onChange={(e) => {
            setOffset(0);
            setTag(e.target.value);
          }}
          className={selectCls}
        >
          <option value="">All tags</option>
          {(page?.tags ?? []).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by difficulty"
          value={difficulty}
          onChange={(e) => {
            setOffset(0);
            setDifficulty(e.target.value as Difficulty | "");
          }}
          className={selectCls}
        >
          <option value="">All difficulties</option>
          <option value="easy">easy</option>
          <option value="medium">medium</option>
          <option value="hard">hard</option>
        </select>
        <input
          aria-label="Search questions"
          placeholder="Search prompts…"
          value={search}
          onChange={(e) => {
            setOffset(0);
            setSearch(e.target.value);
          }}
          className={`${selectCls} min-w-48 flex-1`}
        />
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {page === null ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : page.items.length === 0 ? (
        <p className="text-sm text-zinc-500">No questions match.</p>
      ) : (
        <>
          <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
            {page.items.map((question) => (
              <li key={question.id} className={`p-4 ${question.blocked ? "opacity-60" : ""}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="font-medium text-zinc-900 dark:text-zinc-50">
                    {question.prompt_md}
                  </p>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${DIFFICULTY_TONES[question.difficulty]}`}
                    >
                      {question.difficulty}
                    </span>
                    <button
                      type="button"
                      disabled={busyId === question.id}
                      onClick={() => toggleBlock(question.id, question.blocked)}
                      className="rounded-md border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    >
                      {question.blocked ? "Unblock" : "Block"}
                    </button>
                  </div>
                </div>
                <ul className="mt-1.5 grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
                  {Object.entries(question.options).map(([key, text]) => (
                    <li
                      key={key}
                      className={
                        key === question.correct_key
                          ? "text-green-700 dark:text-green-400"
                          : "text-zinc-600 dark:text-zinc-400"
                      }
                    >
                      {`${key === question.correct_key ? "✓" : "·"} ${key}) ${text}`}
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-zinc-400">
                  {[...question.tags, `${question.time_limit_seconds}s`, question.id].join(" · ")}
                </p>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between text-sm text-zinc-500">
            <span>{`${offset + 1}–${offset + page.items.length} of ${page.total}`}</span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded-md border border-zinc-300 px-2 py-1 hover:bg-zinc-100 disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= page.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded-md border border-zinc-300 px-2 py-1 hover:bg-zinc-100 disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function CompanyQuestions() {
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
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-zinc-500">
          Private to your company; mixed into quizzes whose tags match. The open-source bank
          covers general topics — add questions about your stack and domain here.
        </p>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="shrink-0 rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
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
    </div>
  );
}

export default function QuestionsPage() {
  const [tab, setTab] = useState<"bank" | "company">("bank");

  const tabCls = (active: boolean) =>
    `rounded-md px-3 py-1.5 text-sm font-medium ${
      active
        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
        : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
    }`;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Questions</h1>
        <div className="flex gap-1 rounded-lg border border-zinc-200 p-1 dark:border-zinc-800">
          <button type="button" onClick={() => setTab("bank")} className={tabCls(tab === "bank")}>
            Open bank
          </button>
          <button
            type="button"
            onClick={() => setTab("company")}
            className={tabCls(tab === "company")}
          >
            Company questions
          </button>
        </div>
      </div>
      {tab === "bank" ? <BankBrowser /> : <CompanyQuestions />}
    </section>
  );
}
