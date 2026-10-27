/** Metric definitions for the job overview (spec job posts v2 section 6),
 * written once and shown in tooltips. Counts only, rule 5: nothing here
 * ranks, passes or recommends. */

/** apply rate is noise under this many views in the same period */
export const APPLY_RATE_MIN_VIEWS = 20;
/** `ref:<domain>` rows are advisory (decision JP8): hide the thin ones unless
 * they produced an application */
export const REF_ROW_MIN_VIEWS = 5;

export const VIEWS_TOOLTIP =
  "Page loads by people. Bots, link prefetches and your own signed-in visits on this domain are excluded. Not unique.";

export const APPLY_RATE_TOOLTIP = `Applications divided by views over the same period; shown from ${APPLY_RATE_MIN_VIEWS} views.`;

/** The one window every "30d" tile describes: UTC calendar days, the same
 * days as the daily chart, never a rolling now-minus-30-days. */
export const WINDOW_30D = "Today and the 29 days before it (UTC).";

export const APPLICATIONS_TOOLTIP =
  "Applications received today and the 29 days before it (UTC), the same days as the chart.";

/** Why a job has no views at all (spec section 7 empty states):
 * `share` on a live job with nothing counted, `closed` when there is nothing
 * left to share, `pre-counter` when applications came in before page views
 * existed (v0.4.0), so a share prompt would be the wrong answer. */
export type ViewsEmptyKind = "share" | "closed" | "pre-counter";

export const VIEWS_EMPTY_COPY: Record<ViewsEmptyKind, string> = {
  share: "No views yet. Share it:",
  closed: "No views were counted.",
  "pre-counter":
    "No views counted yet. Page views are counted from the 0.4.0 update on; earlier applications have none beside them.",
};

export function viewsEmptyState(
  status: "draft" | "published" | "closed",
  viewsTotal: number,
  applicationsTotal: number,
): ViewsEmptyKind | null {
  if (viewsTotal > 0) return null;
  if (status === "closed") return "closed";
  if (applicationsTotal > 0) return "pre-counter";
  return "share";
}

/** Why the apply rate is not shown, or null when it is. Jobs that predate
 * the counter carry applications with no matching views: a rate over 100%
 * would read as a bug, so it stays hidden until views catch up. */
export function applyRateReason(views: number, applications: number): string | null {
  if (views < APPLY_RATE_MIN_VIEWS) return "under 20 views";
  if (applications > views) return "applications outnumber counted views";
  return null;
}

export function applyRate(views: number, applications: number): string | null {
  if (applyRateReason(views, applications) !== null) return null;
  return `${Math.round((100 * applications) / views)}%`;
}

export interface SourceRow {
  source: string;
  views: number;
  applications: number;
  applyRate: string | null;
}

export function sourceRows(
  views: Record<string, number>,
  applications: Record<string, number>,
): SourceRow[] {
  const names = new Set([...Object.keys(views), ...Object.keys(applications)]);
  return [...names]
    .map((source) => {
      const v = views[source] ?? 0;
      const a = applications[source] ?? 0;
      return { source, views: v, applications: a, applyRate: applyRate(v, a) };
    })
    .filter((row) => !(row.source.startsWith("ref:") && row.views < REF_ROW_MIN_VIEWS && row.applications === 0))
    .sort(
      (x, y) =>
        y.views - x.views || y.applications - x.applications || x.source.localeCompare(y.source),
    );
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}
