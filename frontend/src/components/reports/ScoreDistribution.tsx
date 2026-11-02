import type { StatsOverview } from "@/lib/api";

/** Score distribution of completed assessments, ten 10-point bins in one
 * colour. No pass line, no pass rate: the tool never auto-rejects, so no
 * score reads as a verdict. */
export function ScoreDistribution({ quiz }: { quiz: StatsOverview["quiz"] }) {
  const dist = quiz.score_distribution.length === 10 ? quiz.score_distribution : Array(10).fill(0);
  const total = dist.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...dist);
  const median = quiz.median_score === null || quiz.attempts_completed < 3 ? null : Math.round(quiz.median_score * 100);
  const binLabel = (i: number) => `${i * 10}-${i === 9 ? 100 : i * 10 + 9}`;

  return (
    <section className="card min-w-0 px-5 py-[18px]">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-heading text-[15px] font-semibold">Score distribution</h2>
        <span className="font-mono text-[11px] text-g500">{quiz.attempts_completed} completed</span>
      </div>
      {total === 0 ? (
        <p className="mt-4 text-sm text-g500">No completed assessments yet.</p>
      ) : (
        <>
          <div
            role="img"
            aria-label={`Score distribution, ${quiz.attempts_completed} completed assessments`}
            className="mt-4"
          >
            <div className="flex h-[120px] items-end border-b border-edge">
              {dist.map((count, i) => (
                <div key={i} title={`${binLabel(i)}: ${count}`} className="flex h-full min-w-0 flex-1 items-end justify-center">
                  <div
                    data-testid="score-bar"
                    className="rounded-t-[4px]"
                    style={{
                      width: "min(24px, calc(100% - 2px))",
                      height: count === 0 ? 0 : `${Math.max(2, (count / max) * 100)}%`,
                      background: "var(--chart-accent)",
                    }}
                  />
                </div>
              ))}
            </div>
            <div className="mt-1.5 flex justify-between font-mono text-[11px] text-g500">
              {[0, 20, 40, 60, 80, 100].map((tick) => (
                <span key={tick}>{tick}</span>
              ))}
            </div>
          </div>
          <p className="mt-2.5 text-[11.5px] text-g600">
            median <b className="font-semibold text-strong">{median ?? "-"}</b> (n = {quiz.attempts_completed})
          </p>
          <details className="mt-2.5">
            <summary className="cursor-pointer text-[11px] text-accent-text">View as table</summary>
            <table className="mt-2 w-full border-collapse text-[11.5px] text-g600">
              <thead>
                <tr className="text-g500">
                  <th scope="col" className="py-0.5 text-left font-normal">Score</th>
                  <th scope="col" className="py-0.5 text-right font-normal">Candidates</th>
                </tr>
              </thead>
              <tbody>
                {dist.map((count, i) => (
                  <tr key={i} className="border-t border-divider">
                    <th scope="row" className="py-0.5 text-left font-normal">{binLabel(i)}</th>
                    <td className="py-0.5 text-right">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}
