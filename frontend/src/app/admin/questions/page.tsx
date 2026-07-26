"use client";

import { useCallback, useEffect, useState } from "react";

import { ChevronDown, Plus, Search } from "lucide-react";

import { DifficultyDots } from "@/components/DifficultyDots";
import {
  questions,
  type BankPage,
  type Difficulty,
  type QuestionOut,
} from "@/lib/api";

/** Question library, handoff screen 09: card table with the 5-dot difficulty
 * scale, Source pill, handoff-styled search + filters. Bulk-select
 * ("Add to questionnaire") is explicitly D4 and lands with questionnaires. */

const OPTION_KEYS = ["a", "b", "c", "d"] as const;
const PAGE_SIZE = 25;

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm outline-none focus:border-g400";
const filterCls =
  "inline-flex h-[34px] items-center gap-1.5 rounded-md border border-edge bg-surface px-3 text-[13px] text-g700 outline-none focus:border-g400";
const labelCls = "text-[13.5px] font-medium";
const rowActionCls =
  "inline-flex h-7 items-center rounded-sm border border-edge bg-surface px-2.5 text-[12px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50";

function SourcePill({ label }: { label: "open bank" | "company" | "retired" }) {
  const cls =
    label === "company"
      ? "border-accent/30 bg-accent/10 text-accent"
      : label === "retired"
        ? "border-edge bg-muted-fill text-g500"
        : "border-edge text-g600";
  return (
    <span
      className={`inline-flex h-5 items-center rounded-full border px-2 text-[11px] font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

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

  const filtersActive = tag !== "" || difficulty !== "" || search !== "";

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
      <p className="text-sm text-g500">
        The open-source bank your quizzes draw from. Blocking a question here removes it from
        every quiz across your company; per-job exclusions live on each job&apos;s quiz preview.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-[260px]">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-[11px] h-[15px] w-[15px] -translate-y-1/2 text-g400"
          />
          <input
            aria-label="Search questions"
            placeholder="Search questions…"
            value={search}
            onChange={(event) => {
              setOffset(0);
              setSearch(event.target.value);
            }}
            className="h-[34px] w-full rounded-md border border-edge bg-surface pr-3 pl-[34px] text-[13.5px] outline-none focus:border-g400"
          />
        </div>
        <div className="relative">
          <select
            aria-label="Filter by tag"
            value={tag}
            onChange={(event) => {
              setOffset(0);
              setTag(event.target.value);
            }}
            className={`${filterCls} appearance-none pr-8`}
          >
            <option value="">Tag: all</option>
            {(page?.tags ?? []).map((t) => (
              <option key={t} value={t}>
                Tag: {t}
              </option>
            ))}
          </select>
          <ChevronDown
            aria-hidden
            className="pointer-events-none absolute top-1/2 right-2.5 h-3.5 w-3.5 -translate-y-1/2 text-g500"
          />
        </div>
        <div className="relative">
          <select
            aria-label="Filter by difficulty"
            value={difficulty}
            onChange={(event) => {
              setOffset(0);
              setDifficulty(event.target.value === "" ? "" : Number(event.target.value));
            }}
            className={`${filterCls} appearance-none pr-8`}
          >
            <option value="">Difficulty: any</option>
            {[1, 2, 3, 4, 5].map((level) => (
              <option key={level} value={level}>
                Difficulty: {level}
              </option>
            ))}
          </select>
          <ChevronDown
            aria-hidden
            className="pointer-events-none absolute top-1/2 right-2.5 h-3.5 w-3.5 -translate-y-1/2 text-g500"
          />
        </div>
        {filtersActive ? (
          <button
            type="button"
            onClick={() => {
              setTag("");
              setDifficulty("");
              setSearch("");
              setOffset(0);
            }}
            className="ml-1 text-[12.5px] font-medium text-accent hover:underline"
          >
            Clear
          </button>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {page === null ? (
        <div aria-busy="true" className="space-y-2">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-muted-fill" />
          ))}
        </div>
      ) : page.items.length === 0 ? (
        <p className="text-sm text-g500">No questions match.</p>
      ) : (
        <>
          <div className="card overflow-hidden">
            <table className="w-full text-[13.5px]">
              <thead>
                <tr className="border-b border-divider text-left text-[12.5px] font-medium text-g500">
                  <th className="h-10 px-4 font-medium">Question</th>
                  <th className="h-10 px-3 font-medium">Difficulty</th>
                  <th className="h-10 px-3 font-medium">Source</th>
                  <th className="h-10 px-3" />
                </tr>
              </thead>
              <tbody>
                {page.items.map((question) => (
                  <tr
                    key={question.id}
                    className={`border-b border-divider last:border-b-0 hover:bg-hover-fill ${
                      question.blocked ? "opacity-60" : ""
                    }`}
                  >
                    <td className="max-w-[520px] px-4 py-3 align-middle">
                      <p className="truncate font-medium">{question.prompt_md}</p>
                      <p className="mt-1 truncate font-mono text-[10.5px] text-g400">
                        {[...question.tags, `${question.time_limit_seconds}s`].join(" · ")}
                      </p>
                    </td>
                    <td className="px-3 py-3 align-middle whitespace-nowrap">
                      <span className="inline-flex items-center gap-2">
                        <DifficultyDots level={question.difficulty} />
                        <span className="font-mono text-[11px] text-g500">
                          d{question.difficulty}
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-3 align-middle whitespace-nowrap">
                      <SourcePill label="open bank" />
                    </td>
                    <td className="px-3 py-3 text-right align-middle">
                      <button
                        type="button"
                        disabled={busyId === question.id}
                        onClick={() => toggleBlock(question.id, question.blocked)}
                        className={rowActionCls}
                      >
                        {question.blocked ? "Unblock" : "Block"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-sm text-g500">
            <span className="font-mono text-[11.5px]">
              {`${offset + 1}–${offset + page.items.length} of ${page.total}`}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className={rowActionCls}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= page.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className={rowActionCls}
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
        difficulty: Number(str("difficulty") || "3"),
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
        <p className="text-sm text-g500">
          Private to your company; mixed into quizzes whose tags match. The open-source bank
          covers general topics — add questions about your stack and domain here.
        </p>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-inverse pr-3 pl-2 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94]"
        >
          <Plus aria-hidden className="h-[15px] w-[15px]" />
          {showForm ? "Cancel" : "New question"}
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {showForm ? (
        <form onSubmit={handleCreate} className="card space-y-4 p-5">
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Question (markdown, answerable in ~15s)</span>
            <textarea
              name="prompt_md"
              required
              minLength={10}
              rows={2}
              className="w-full rounded-md border border-edge bg-transparent px-3 py-2 text-sm outline-none focus:border-g400"
            />
          </label>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {OPTION_KEYS.map((key) => (
              <label key={key} className="flex flex-col gap-2">
                <span className={labelCls}>Option {key.toUpperCase()}</span>
                <input name={`option_${key}`} required className={inputCls} />
              </label>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <label className="flex flex-col gap-2">
              <span className={labelCls}>Correct</span>
              <select name="correct_key" className={inputCls} defaultValue="a">
                {OPTION_KEYS.map((key) => (
                  <option key={key} value={key}>
                    {key.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-2">
              <span className={labelCls}>Difficulty</span>
              <select name="difficulty" className={inputCls} defaultValue="3">
                {[1, 2, 3, 4, 5].map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-2">
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
            <label className="flex flex-col gap-2">
              <span className={labelCls}>Tags</span>
              <input name="tags" required placeholder="python, internal" className={inputCls} />
            </label>
          </div>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Explanation (shown to reviewers)</span>
            <textarea
              name="explanation_md"
              rows={2}
              className="w-full rounded-md border border-edge bg-transparent px-3 py-2 text-sm outline-none focus:border-g400"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="inline-flex h-8 items-center justify-center rounded-md bg-inverse px-3 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
          >
            {busy ? "…" : "Create question"}
          </button>
        </form>
      ) : null}

      {items === null ? (
        <div aria-busy="true" className="space-y-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-muted-fill" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-g500">No company questions yet.</p>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-[13.5px]">
            <thead>
              <tr className="border-b border-divider text-left text-[12.5px] font-medium text-g500">
                <th className="h-10 px-4 font-medium">Question</th>
                <th className="h-10 px-3 font-medium">Difficulty</th>
                <th className="h-10 px-3 font-medium">Source</th>
                <th className="h-10 px-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((question) => (
                <tr
                  key={question.id}
                  className="border-b border-divider last:border-b-0 hover:bg-hover-fill"
                >
                  <td className="max-w-[520px] px-4 py-3 align-middle">
                    <p className="truncate font-medium">{question.prompt_md}</p>
                    <p className="mt-1 truncate font-mono text-[10.5px] text-g400">
                      {[...question.tags, `${question.time_limit_seconds}s`].join(" · ")}
                    </p>
                  </td>
                  <td className="px-3 py-3 align-middle whitespace-nowrap">
                    <span className="inline-flex items-center gap-2">
                      <DifficultyDots level={question.difficulty} />
                      <span className="font-mono text-[11px] text-g500">
                        d{question.difficulty}
                      </span>
                    </span>
                  </td>
                  <td className="px-3 py-3 align-middle whitespace-nowrap">
                    <SourcePill label={question.status === "retired" ? "retired" : "company"} />
                  </td>
                  <td className="px-3 py-3 text-right align-middle">
                    {question.status === "active" ? (
                      <button
                        type="button"
                        onClick={() => retire(question.id)}
                        className={rowActionCls}
                      >
                        Retire
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function QuestionsPage() {
  const [tab, setTab] = useState<"bank" | "company">("bank");

  const tabCls = (active: boolean) =>
    `inline-flex h-7 items-center rounded-full px-[11px] text-[12.5px] font-medium ${
      active
        ? "bg-inverse text-inverse-foreground"
        : "border border-edge bg-surface text-g700 hover:border-g400"
    }`;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">
          Question library
        </h1>
        <div className="flex gap-1.5">
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
