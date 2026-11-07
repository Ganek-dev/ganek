import type { CohortKpis } from "@/lib/api";

/** Labels closer than this (percent of the strip) to the previous label are
 * dropped; the dot stays and the table below lists every hire. */
const LABEL_GAP = 9;

/** Axis end: a third past the slowest hire, rounded up to 5 days. */
export function axisMax(days: number[]): number {
  const max = Math.max(0, ...days);
  return Math.max(5, Math.ceil((max * 1.4) / 5) * 5);
}

const dayWord = (d: number) => (d === 1 ? "day" : "days");

/** One dot per hire, days from application to hired, on a hairline from 0.
 * Hires on the same day share a dot. No average line: the median sits in
 * text under the strip with its n, "-" below n = 3. */
export function TimeToHire({ cohort }: { cohort: CohortKpis }) {
  const days = cohort.hire_days.map((d) => Math.round(d));
  const end = axisMax(days);
  const groups: { day: number; count: number }[] = [];
  for (const day of days) {
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.count += 1;
    else groups.push({ day, count: 1 });
  }
  let lastLabel = -Infinity;
  const dots = groups.map((g) => {
    const left = (g.day / end) * 100;
    const labelled = left - lastLabel >= LABEL_GAP;
    if (labelled) lastLabel = left;
    return { ...g, left, labelled };
  });
  const median = cohort.median_time_to_hire_days;

  return (
    <section className="card min-w-0 px-5 py-[18px]">
      <h2 className="font-heading text-[15px] font-semibold">Time to hire</h2>
      <p className="mt-0.5 text-[11px] text-g500">one dot per hire, days from application</p>
      {days.length === 0 ? (
        <p className="mt-4 text-[12.5px] text-g600">No hires in this period.</p>
      ) : (
        <>
          <div
            role="img"
            aria-label={`Hires after ${listDays(days)} days`}
            className="relative mt-[18px] h-9"
          >
            <div aria-hidden className="absolute inset-x-0 top-6 h-px bg-edge" />
            {dots.map((g) => (
              <div
                key={g.day}
                data-testid="hire-dot"
                className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-1"
                style={{ left: `${g.left}%` }}
              >
                <span className="h-[15px] font-mono text-[11px] leading-[15px] whitespace-nowrap text-g600">
                  {g.labelled ? `${g.day} d${g.count > 1 ? ` x${g.count}` : ""}` : ""}
                </span>
                <span
                  title={
                    g.count > 1
                      ? `${g.count} hires after ${g.day} ${dayWord(g.day)}`
                      : `Hired after ${g.day} ${dayWord(g.day)}`
                  }
                  className="relative size-3 rounded-full"
                  style={{ background: "var(--chart-accent)", boxShadow: "0 0 0 2px var(--surface)" }}
                />
              </div>
            ))}
          </div>
          <div className="mt-1 flex justify-between font-mono text-[11px] text-g500">
            <span>0</span>
            <span>{end} d</span>
          </div>
        </>
      )}
      <p className="mt-3 font-mono text-[11.5px] text-g600">
        {median === null
          ? `Median - (n = ${cohort.hires_n})`
          : `Median ${Number(median.toFixed(1))} ${dayWord(median)} (n = ${cohort.hires_n})`}
      </p>
      {days.length > 0 ? (
        <details className="mt-2.5">
          <summary className="cursor-pointer text-[11px] text-accent-text">View as table</summary>
          <table className="mt-2 w-full border-collapse text-[11.5px] text-g600">
            <thead>
              <tr className="text-g500">
                <th scope="col" className="py-0.5 text-left font-normal">Days to hire</th>
                <th scope="col" className="py-0.5 text-right font-normal">Hires</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.day} className="border-t border-divider">
                  <th scope="row" className="py-0.5 text-left font-normal">{g.day}</th>
                  <td className="py-0.5 text-right">{g.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </section>
  );
}

function listDays(days: number[]): string {
  if (days.length === 1) return String(days[0]);
  return `${days.slice(0, -1).join(", ")} and ${days[days.length - 1]}`;
}
