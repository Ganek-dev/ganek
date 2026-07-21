"use client";

import { useState } from "react";

import type { EmploymentType, JobInput, JobOut, QuizConfig, RemotePolicy } from "@/lib/api";

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
  "w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
const labelCls = "text-sm font-medium text-zinc-700 dark:text-zinc-300";

export function JobForm({
  initial,
  submitLabel,
  onSubmit,
}: {
  initial?: JobOut;
  submitLabel: string;
  onSubmit: (values: JobInput) => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        enabled: data.get("quiz_enabled") === "on",
        tags: quizTags.length > 0 ? quizTags : null,
        question_count: Number(str("quiz_question_count") || "6"),
        include_company_questions: true,
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
        tags: str("tags")
          .split(",")
          .map((t) => t.trim().toLowerCase())
          .filter(Boolean),
        quiz_config,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl space-y-4">
      <label className="block space-y-1">
        <span className={labelCls}>Title</span>
        <input name="title" required defaultValue={initial?.title} className={inputCls} />
      </label>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <label className="block space-y-1">
          <span className={labelCls}>Location</span>
          <input name="location" defaultValue={initial?.location} className={inputCls} />
        </label>
        <label className="block space-y-1">
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
        <label className="block space-y-1">
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
        <label className="block space-y-1">
          <span className={labelCls}>Salary min</span>
          <input
            name="salary_min"
            type="number"
            min={0}
            defaultValue={initial?.salary_min ?? ""}
            className={inputCls}
          />
        </label>
        <label className="block space-y-1">
          <span className={labelCls}>Salary max</span>
          <input
            name="salary_max"
            type="number"
            min={0}
            defaultValue={initial?.salary_max ?? ""}
            className={inputCls}
          />
        </label>
        <label className="block space-y-1">
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

      <label className="block space-y-1">
        <span className={labelCls}>Tags (comma-separated, drive quiz matching later)</span>
        <input
          name="tags"
          placeholder="python, fastapi, backend"
          defaultValue={initial?.tags.join(", ")}
          className={inputCls}
        />
      </label>

      <label className="block space-y-1">
        <span className={labelCls}>Description (markdown)</span>
        <textarea
          name="description_md"
          rows={10}
          defaultValue={initial?.description_md}
          className={inputCls}
        />
      </label>

      <fieldset className="space-y-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
        <legend className="px-1 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
          Screening quiz
        </legend>
        <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
          <input
            name="quiz_enabled"
            type="checkbox"
            defaultChecked={initial?.quiz_config.enabled ?? false}
          />
          Ask candidates a short timed quiz after they apply
        </label>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block space-y-1">
            <span className={labelCls}>Questions</span>
            <input
              name="quiz_question_count"
              type="number"
              min={1}
              max={20}
              defaultValue={initial?.quiz_config.question_count ?? 6}
              className={inputCls}
            />
          </label>
          <label className="block space-y-1">
            <span className={labelCls}>Quiz tags (defaults to job tags)</span>
            <input
              name="quiz_tags"
              placeholder="python, asyncio"
              defaultValue={initial?.quiz_config.tags?.join(", ") ?? ""}
              className={inputCls}
            />
          </label>
        </div>
      </fieldset>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
      >
        {busy ? "…" : submitLabel}
      </button>
    </form>
  );
}
