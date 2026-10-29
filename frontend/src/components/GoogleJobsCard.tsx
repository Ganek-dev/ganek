"use client";

import { useEffect, useState } from "react";

import { AlertTriangle, Check, ExternalLink } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import { api, publicPages, type CompanySummary, type JobOut } from "@/lib/api";
import { jobPostingChecks, jobPostingJsonLd, type JobPostingJsonLd } from "@/lib/job-posting";
import { EMBED_DOCS_URL } from "@/lib/share-links";

/** "Google Jobs markup" rail card on the job overview: the JobPosting
 * JSON-LD the public job page emits, built from the same public payloads
 * the page renders from, with Google's required-field check, a copy button
 * and the docs link. A demo instance switches the markup off (fictional
 * vacancies, search engines asked to stay away), and the card says so. */

export const GOOGLE_JOBS_DOCS_URL = `${EMBED_DOCS_URL}#google-jobs-markup`;

type State =
  | { kind: "loading" }
  | { kind: "demo" }
  | { kind: "error"; message: string }
  | { kind: "ready"; jsonLd: JobPostingJsonLd };

const LOAD_FAILED = "Could not load the public page for this job.";

export function GoogleJobsCard({
  job,
  company,
  urlFailed,
}: {
  job: JobOut;
  company: CompanySummary | null;
  /** the company summary failed: nothing public can be fetched */
  urlFailed: boolean;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const live = job.status === "published";
  const mode = company?.mode ?? null;
  const slug = company?.slug ?? null;

  useEffect(() => {
    if (!live || mode === null || slug === null) return;
    let cancelled = false;
    api
      .providers()
      .then(async (providers): Promise<State> => {
        if (providers.demo) return { kind: "demo" };
        const [publicCompany, publicJob] = await Promise.all([
          publicPages.company(mode, slug),
          publicPages.job(mode, slug, job.slug),
        ]);
        return { kind: "ready", jsonLd: jobPostingJsonLd(publicCompany, publicJob) };
      })
      .catch((): State => ({ kind: "error", message: LOAD_FAILED }))
      .then((next) => {
        if (!cancelled) setState(next);
      });
    return () => {
      cancelled = true;
    };
  }, [live, mode, slug, job.slug]);

  return (
    <div className="card px-5 py-[18px]">
      <div className="flex items-center justify-between gap-3">
        <span className="font-heading text-[15px] font-semibold whitespace-nowrap">
          Google Jobs markup
        </span>
        <a
          href={GOOGLE_JOBS_DOCS_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-accent hover:underline"
        >
          Docs
          <ExternalLink aria-hidden className="h-3 w-3" />
        </a>
      </div>
      <div className="mt-3">{body()}</div>
    </div>
  );

  function body() {
    if (!live) {
      return (
        <p className="text-sm text-g500">
          {job.status === "closed"
            ? "Removed when a job closes."
            : "Appears once the job is published."}
        </p>
      );
    }
    if (company === null) {
      return urlFailed ? (
        <p className="text-sm text-g500">Markup loads with the company.</p>
      ) : (
        <Skeleton />
      );
    }
    switch (state.kind) {
      case "loading":
        return <Skeleton />;
      case "demo":
        return (
          <p className="text-sm leading-[21px] text-g600">
            Off on the demo. These vacancies are fictional and the demo asks search engines
            to stay away, so the JobPosting markup is not emitted here. Every published job
            on your own instance ships it.
          </p>
        );
      case "error":
        return <p className="text-sm text-g500">{state.message}</p>;
      case "ready":
        return <Markup jsonLd={state.jsonLd} />;
    }
  }
}

function Skeleton() {
  return (
    <div aria-busy="true" aria-label="Loading markup" className="space-y-2">
      <div className="h-5 w-48 animate-pulse rounded-sm bg-muted-fill" />
      <div className="h-24 animate-pulse rounded-md bg-muted-fill" />
    </div>
  );
}

function Markup({ jsonLd }: { jsonLd: JobPostingJsonLd }) {
  const checks = jobPostingChecks(jsonLd);
  const required = checks.filter((check) => check.required);
  const recommended = checks.filter((check) => !check.required);
  const requiredOk = required.filter((check) => check.ok).length;
  const recommendedOk = recommended.filter((check) => check.ok).length;
  const complete = requiredOk === required.length;
  const missing = checks.filter((check) => !check.ok);
  const compact = JSON.stringify(jsonLd);

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2">
        {complete ? (
          <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        ) : (
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        )}
        <div>
          <p className="text-[13.5px] font-medium">
            {requiredOk} of {required.length} required fields present
          </p>
          <p className="font-mono text-[11px] text-g500">
            {recommendedOk} of {recommended.length} recommended
          </p>
        </div>
      </div>
      {missing.length > 0 ? (
        <ul className="space-y-1">
          {missing.map((check) => (
            <li key={check.field} className="text-[12.5px] leading-[19px] text-g600">
              <span className="font-mono text-[11px] text-g500">{check.field}</span>
              {check.required ? "" : " (recommended)"}: {check.hint}
            </li>
          ))}
        </ul>
      ) : null}
      <pre
        data-testid="google-jobs-json"
        className="max-h-56 overflow-auto rounded-md border border-edge bg-muted-fill p-3 font-mono text-[11px] leading-[16px] text-g700"
      >
        {JSON.stringify(jsonLd, null, 2)}
      </pre>
      <CopyButton
        text={compact}
        label="Copy JSON-LD"
        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-edge bg-surface px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
      >
        Copy JSON-LD
      </CopyButton>
    </div>
  );
}
