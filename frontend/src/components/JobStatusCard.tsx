import { useEffect, useState } from "react";

import { ExternalLink } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import { StatusPill } from "@/components/JobStatus";
import { api, type JobOut } from "@/lib/api";

/** Status card (screen 08 rail): current status, Publish / Close, live
 * since, and the candidate view: a plain link on a live job (when the
 * caller knows the public URL), a 7-day preview link otherwise (spec job
 * posts v2 5.3). Shared by the editor and the job overview. */

const actionCls =
  "inline-flex h-7 items-center gap-1 rounded-sm border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50";

export function JobStatusCard({
  job,
  publicUrl = null,
  onError,
  onChanged,
}: {
  job: JobOut;
  /** the live job page; the editor does not know it and passes nothing */
  publicUrl?: string | null;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const live = job.status === "published";
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    // a live job never shows the preview actions, so a stale URL is unused
    if (live) return;
    let cancelled = false;
    api.jobs
      .previewLink(job.id)
      .then((link) => {
        if (!cancelled) setPreviewUrl(link.url);
      })
      .catch(() => {
        if (!cancelled) setPreviewUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [job.id, live]);

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Action failed");
    }
  }

  return (
    <div className="card px-5 py-[18px]">
      <span className="font-heading text-[15px] font-semibold">Status</span>
      <div className="mt-3 flex items-center justify-between">
        <StatusPill status={job.status} />
        {live ? (
          <button
            type="button"
            onClick={() => act(() => api.jobs.close(job.id))}
            className={actionCls}
          >
            Close
          </button>
        ) : (
          <button
            type="button"
            onClick={() => act(() => api.jobs.publish(job.id))}
            className={actionCls}
          >
            Publish
          </button>
        )}
      </div>
      {job.published_at ? (
        <p className="mt-2.5 font-mono text-[11px] text-g500">
          Live since{" "}
          {new Date(job.published_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </p>
      ) : null}
      {live && publicUrl ? (
        <a href={publicUrl} target="_blank" rel="noreferrer" className={`mt-3 ${actionCls}`}>
          View as candidate
          <ExternalLink aria-hidden className="h-3 w-3" />
        </a>
      ) : null}
      {!live ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={previewUrl === null}
            onClick={() => {
              if (previewUrl !== null) window.open(previewUrl, "_blank", "noopener");
            }}
            className={actionCls}
          >
            View as candidate
            <ExternalLink aria-hidden className="h-3 w-3" />
          </button>
          {previewUrl !== null ? (
            <>
              <CopyButton text={previewUrl} label="Copy preview link" />
              <span className="font-mono text-[11px] text-g500">link valid 7 days</span>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
