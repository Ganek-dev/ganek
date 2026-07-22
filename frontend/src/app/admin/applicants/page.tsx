"use client";

import { useCallback, useEffect, useState } from "react";

import {
  api,
  applications,
  type ApplicationOut,
  type ApplicationStage,
  type JobOut,
  type QuizResult,
} from "@/lib/api";

const STAGES: ApplicationStage[] = [
  "new",
  "screening",
  "interview",
  "offer",
  "hired",
  "rejected",
];

const selectCls =
  "rounded-md border border-zinc-300 px-2 py-1 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";

function QuizBadge({ result }: { result: QuizResult | null }) {
  if (result === null) {
    return null;
  }
  if (result.status !== "completed" || result.score === null) {
    return (
      <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
        quiz {result.status.replace("_", " ")}
      </span>
    );
  }
  const percent = Math.round(result.score * 100);
  const total = result.question_ids.length;
  const correct = Math.round(result.score * total);
  const tone =
    percent >= 70
      ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
      : percent >= 40
        ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
        : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  const breakdown = Object.entries(result.per_tag_scores)
    .map(([tag, bucket]) => `${tag}: ${bucket.correct}/${bucket.total}`)
    .join(" · ");
  const flags = result.integrity.flags ?? [];
  return (
    <>
      <span
        title={breakdown}
        className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      >
        quiz {percent}% ({correct}/{total})
      </span>
      {flags.length > 0 ? (
        <span
          title={flags.join(" · ")}
          className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-800 dark:bg-orange-900 dark:text-orange-200"
        >
          ⚠ {flags.length}
        </span>
      ) : null}
    </>
  );
}

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

export default function ApplicantsPage() {
  const [items, setItems] = useState<ApplicationOut[] | null>(null);
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [stageFilter, setStageFilter] = useState<ApplicationStage | "">("");
  const [jobFilter, setJobFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    applications
      .list({
        stage: stageFilter === "" ? undefined : stageFilter,
        job_id: jobFilter === "" ? undefined : jobFilter,
      })
      .then(setItems)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load applications"),
      );
  }, [stageFilter, jobFilter]);

  useEffect(reload, [reload]);
  useEffect(() => {
    api.jobs.list().then(setJobs).catch(() => setJobs([]));
  }, []);

  const jobTitle = (id: string) => jobs.find((j) => j.id === id)?.title ?? "—";

  async function changeStage(id: string, stage: ApplicationStage) {
    setError(null);
    try {
      await applications.setStage(id, stage);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stage change failed");
    }
  }

  async function downloadCv(id: string) {
    setError(null);
    try {
      const { download_url } = await applications.cvUrl(id);
      window.open(download_url, "_blank", "noopener");
    } catch (err) {
      setError(err instanceof Error ? err.message : "CV download failed");
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Applicants</h1>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-sm text-zinc-600 dark:text-zinc-400">
            Job
            <select
              value={jobFilter}
              onChange={(e) => setJobFilter(e.target.value)}
              className={selectCls}
            >
              <option value="">All</option>
              {jobs.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.title}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1 text-sm text-zinc-600 dark:text-zinc-400">
            Stage
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value as ApplicationStage | "")}
              className={selectCls}
            >
              <option value="">All</option>
              {STAGES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {items === null ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-zinc-500">No applications match.</p>
      ) : (
        <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
          {items.map((app) => (
            <li key={app.id} className="space-y-2 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium text-zinc-900 dark:text-zinc-50">
                    {app.candidate.name}
                    <span className="ml-2 text-sm font-normal text-zinc-500">
                      {app.candidate.email}
                    </span>
                  </p>
                  <p className="text-sm text-zinc-500">
                    {jobTitle(app.job_id)} · applied{" "}
                    {new Date(app.created_at).toLocaleDateString("en-US")}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <QuizBadge result={app.quiz_attempt} />
                  <select
                    aria-label={`Stage for ${app.candidate.name}`}
                    value={app.stage}
                    onChange={(e) => changeStage(app.id, e.target.value as ApplicationStage)}
                    className={selectCls}
                  >
                    {STAGES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => downloadCv(app.id)}
                    className="rounded-md border border-zinc-300 px-2 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  >
                    CV ({formatBytes(app.cv_size)})
                  </button>
                </div>
              </div>
              {app.message ? (
                <p className="text-sm text-zinc-600 dark:text-zinc-400">{app.message}</p>
              ) : null}
              {Object.keys(app.candidate.links).length > 0 ? (
                <p className="flex gap-3 text-sm">
                  {Object.entries(app.candidate.links).map(([kind, url]) => (
                    <a
                      key={kind}
                      href={url}
                      rel="noopener noreferrer"
                      target="_blank"
                      className="text-zinc-600 underline dark:text-zinc-400"
                    >
                      {kind}
                    </a>
                  ))}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
