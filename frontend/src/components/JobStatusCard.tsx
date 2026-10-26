import { StatusPill } from "@/components/JobStatus";
import { api, type JobOut } from "@/lib/api";

/** Status card (screen 08 rail): current status, Publish / Close, live
 * since. Shared by the editor and the job overview. */

export function JobStatusCard({
  job,
  onError,
  onChanged,
}: {
  job: JobOut;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
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
        {job.status !== "published" ? (
          <button
            type="button"
            onClick={() => act(() => api.jobs.publish(job.id))}
            className="inline-flex h-7 items-center rounded-sm border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
          >
            Publish
          </button>
        ) : (
          <button
            type="button"
            onClick={() => act(() => api.jobs.close(job.id))}
            className="inline-flex h-7 items-center rounded-sm border border-edge px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
          >
            Close
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
    </div>
  );
}
