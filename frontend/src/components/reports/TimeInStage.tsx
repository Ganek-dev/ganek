import type { ApplicationStage, StageTime } from "@/lib/api";

const LABEL: Partial<Record<ApplicationStage, string>> = {
  new: "New",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
};
const label = (stage: ApplicationStage) => LABEL[stage] ?? stage;

function summary(row: StageTime): string {
  return row.median_days === null
    ? `${label(row.stage)} median -, n = ${row.n}`
    : `${label(row.stage)} median ${row.median_days} days, n = ${row.n}`;
}

/** Median days per stage over completed stays, with n; "-" below n = 3. The
 * oldest live candidate sits beside it: look at the oldest, not the count. */
export function TimeInStage({ rows }: { rows: StageTime[] }) {
  const max = Math.max(0, ...rows.map((r) => r.median_days ?? 0));
  return (
    <section className="card px-5 py-[18px]">
      <h2 className="font-heading text-[15px] font-semibold">Time in stage</h2>
      <p className="mt-0.5 text-[11px] text-g500">median days, completed stays</p>
      <div
        role="img"
        aria-label={`Time in stage: ${rows.map(summary).join("; ")}`}
        className="mt-3.5 flex flex-col gap-3.5"
      >
        {rows.map((row) => (
          <div
            key={row.stage}
            className="grid grid-cols-[72px_minmax(0,220px)_92px_1fr] items-center gap-2.5 max-md:grid-cols-[72px_1fr_92px]"
          >
            <span className="text-[13px] font-medium text-strong">{label(row.stage)}</span>
            <div>
              {row.median_days !== null && max > 0 ? (
                <div
                  data-testid="stage-bar"
                  className="h-3 rounded-r-[4px]"
                  style={{
                    width: `${(row.median_days / max) * 100}%`,
                    background: "var(--chart-accent)",
                  }}
                />
              ) : null}
            </div>
            <span className="font-mono text-[12.5px] whitespace-nowrap text-strong">
              {row.median_days === null ? "-" : `${row.median_days} d`}{" "}
              <span className="text-g500">(n = {row.n})</span>
            </span>
            <span className="text-right text-[11px] whitespace-nowrap text-g500 max-md:col-span-3 max-md:text-left">
              {row.oldest_live_days === null
                ? ""
                : `oldest live candidate: ${row.oldest_live_days} d`}
            </span>
          </div>
        ))}
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] text-accent-text">View as table</summary>
        <table className="mt-2 w-full border-collapse text-[11.5px] text-g600">
          <thead>
            <tr className="text-g500">
              <th scope="col" className="py-0.5 text-left font-normal">Stage</th>
              <th scope="col" className="py-0.5 text-right font-normal">Median days</th>
              <th scope="col" className="py-0.5 text-right font-normal">n</th>
              <th scope="col" className="py-0.5 text-right font-normal">Oldest live (days)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.stage} className="border-t border-divider">
                <th scope="row" className="py-0.5 text-left font-normal">{label(row.stage)}</th>
                <td className="py-0.5 text-right">{row.median_days ?? "-"}</td>
                <td className="py-0.5 text-right">{row.n}</td>
                <td className="py-0.5 text-right">{row.oldest_live_days ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
