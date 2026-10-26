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

export function applyRate(views: number, applications: number): string | null {
  if (views < APPLY_RATE_MIN_VIEWS) return null;
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
