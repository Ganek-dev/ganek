import type { ReportsPeriod, StatsOverview } from "@/lib/api";

const ALL_TIME_WEEKS = 53;

/** Applications per week in one colour. Period "all" can span years, so it
 * shows the last 53 weeks; the other periods show what the API returned. */
export function WeeklyChart({
  weekly,
  period,
}: {
  weekly: StatsOverview["weekly"];
  period: ReportsPeriod;
}) {
  const points = period === "all" ? weekly.slice(-ALL_TIME_WEEKS) : weekly;
  const max = Math.max(1, ...points.map((p) => p.count));
  const every = Math.max(1, Math.ceil(points.length / 12));
  const date = (iso: string) =>
    new Date(iso).toLocaleDateString("en-US", { month: "numeric", day: "numeric", timeZone: "UTC" });
  const total = points.reduce((a, p) => a + p.count, 0);

  return (
    <section className="card min-w-0 px-5 py-[18px]">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-heading text-[15px] font-semibold">Applications per week</h2>
        <span className="font-mono text-[11px] text-g500">
          {period === "all" ? `last ${ALL_TIME_WEEKS} weeks` : `${total} applications`}
        </span>
      </div>
      <div
        role="img"
        aria-label={`Applications per week, ${points.length} weeks, ${total} applications`}
        className="mt-3 flex h-28 items-end gap-1 border-b border-edge"
      >
        {points.map((point, i) => (
          <div key={point.week_start} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
            <div
              data-testid="weekly-bar"
              title={`Week of ${point.week_start}: ${point.count}`}
              className="w-full max-w-6 rounded-t-[4px]"
              style={{
                height: point.count === 0 ? 0 : `${Math.max(3, (point.count / max) * 80)}px`,
                background: "var(--chart-accent)",
              }}
            />
            <span className="h-3 font-mono text-[11px] leading-3 whitespace-nowrap text-g500">
              {i % every === 0 ? date(point.week_start) : ""}
            </span>
          </div>
        ))}
      </div>
      <details className="mt-2.5">
        <summary className="cursor-pointer text-[11px] text-accent-text">View as table</summary>
        <table className="mt-2 w-full border-collapse text-[11.5px] text-g600">
          <thead>
            <tr className="text-g500">
              <th scope="col" className="py-0.5 text-left font-normal">Week of</th>
              <th scope="col" className="py-0.5 text-right font-normal">Applications</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.week_start} className="border-t border-divider">
                <th scope="row" className="py-0.5 text-left font-normal">{point.week_start}</th>
                <td className="py-0.5 text-right">{point.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
