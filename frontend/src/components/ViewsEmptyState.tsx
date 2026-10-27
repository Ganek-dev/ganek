"use client";

import { ShareLinkRows } from "@/components/ShareLinksCard";
import { VIEWS_EMPTY_COPY, type ViewsEmptyKind } from "@/lib/job-metrics";

/** What the job overview says under the daily chart when no view was ever
 * counted (spec job posts v2 section 7, card "Overview empty states"). A
 * live job gets the preset share links right there; a closed job and a job
 * whose applications predate the counter get one neutral sentence and no
 * call to share. */
export function ViewsEmptyState({ kind, jobUrl }: { kind: ViewsEmptyKind; jobUrl: string | null }) {
  return (
    <div>
      <p className="text-sm text-g500">{VIEWS_EMPTY_COPY[kind]}</p>
      {kind !== "share" ? null : jobUrl === null ? (
        <div aria-busy="true" aria-label="Loading share links" className="mt-2 space-y-2">
          {Array.from({ length: 2 }, (_, i) => (
            <div key={i} className="h-5 animate-pulse rounded-sm bg-muted-fill" />
          ))}
        </div>
      ) : (
        <ShareLinkRows jobUrl={jobUrl} className="mt-2 grid gap-2 sm:grid-cols-2" />
      )}
    </div>
  );
}
