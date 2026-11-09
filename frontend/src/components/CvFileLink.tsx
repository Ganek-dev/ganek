"use client";

import { FileText, Loader2, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

import type { ApplicationOut } from "@/lib/api";

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

/** The CV line in the applicant header: a download button, "No CV", or,
 * when the virus scanner flagged the file, a disabled control with the
 * reason (the API answers 409 for that CV anyway). A pending scan or a
 * scanner error keeps the download and says so; a clean scan shows a small
 * shield. A null status (no scanner configured, or a CV from before it was)
 * renders exactly as before. */
export function CvFileLink({
  app,
  onDownload,
}: {
  app: Pick<
    ApplicationOut,
    "id" | "cv_filename" | "cv_size" | "cv_scan_status" | "cv_scan_signature"
  >;
  onDownload: () => void;
}) {
  if (app.cv_filename === null) {
    return (
      <span className="inline-flex items-center gap-1.5 text-g500">
        <FileText aria-hidden className="h-[13px] w-[13px]" />
        No CV
      </span>
    );
  }
  const label = `${app.cv_filename} (${formatBytes(app.cv_size ?? 0)})`;
  const status = app.cv_scan_status ?? null;

  if (status === "infected") {
    const reasonId = `cv-blocked-${app.id}`;
    const signature = app.cv_scan_signature ? ` (${app.cv_scan_signature})` : "";
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled
          aria-describedby={reasonId}
          className="inline-flex cursor-not-allowed items-center gap-1.5 font-medium text-g400 line-through"
        >
          <FileText aria-hidden className="h-[13px] w-[13px]" />
          {label}
        </button>
        <span
          id={reasonId}
          role="note"
          className="inline-flex items-center gap-1 rounded-sm bg-red-50 px-1.5 py-0.5 text-[12px] font-medium text-red-700 dark:bg-red-950/40 dark:text-red-400"
        >
          <ShieldAlert aria-hidden className="h-[12px] w-[12px]" />
          {`Blocked: the virus scanner flagged this CV${signature}. Ask the candidate to upload a new file.`}
        </span>
      </span>
    );
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        onClick={onDownload}
        className="inline-flex items-center gap-1.5 font-medium text-accent hover:underline"
      >
        <FileText aria-hidden className="h-[13px] w-[13px]" />
        {label}
      </button>
      {status === "clean" ? (
        <span
          title="Virus scan: clean"
          className="inline-flex items-center text-emerald-700 dark:text-emerald-400"
        >
          <ShieldCheck aria-hidden className="h-[13px] w-[13px]" />
          <span className="sr-only">Virus scan: clean</span>
        </span>
      ) : null}
      {status === "pending" ? (
        <span className="inline-flex items-center gap-1 text-[12px] text-g500">
          <Loader2 aria-hidden className="h-[12px] w-[12px] animate-spin" />
          Scanning for viruses
        </span>
      ) : null}
      {status === "error" ? (
        <span
          title="The scanner could not check this file after several tries. Open it with care."
          className="inline-flex items-center gap-1 text-[12px] text-amber-700 dark:text-amber-400"
        >
          <ShieldQuestion aria-hidden className="h-[12px] w-[12px]" />
          Not scanned (scanner error)
        </span>
      ) : null}
    </span>
  );
}
