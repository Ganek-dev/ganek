import type { SourceRow } from "@/lib/api";

/** Sources by outcome. "direct" (no recorded source) comes first, the rest
 * keep the API order (applications, descending). */
export function SourcesTable({ rows }: { rows: SourceRow[] }) {
  const sorted = [...rows.filter((r) => r.source === "direct"), ...rows.filter((r) => r.source !== "direct")];
  const th = "pb-2 text-[11px] font-normal text-g500 align-bottom";
  const td = "border-t border-divider py-[9px] pl-2.5 text-right font-mono text-[12.5px] tabular-nums";
  return (
    <section className="card px-5 pt-[18px] pb-2.5">
      <h2 className="font-heading text-[15px] font-semibold">Sources</h2>
      {sorted.length === 0 ? (
        <p className="mt-3 pb-2 text-sm text-g500">No applications in this period.</p>
      ) : (
        <table className="mt-3 w-full border-collapse">
          <thead>
            <tr>
              <th scope="col" className={`${th} text-left`}>Source</th>
              <th scope="col" className={`${th} pl-2.5 text-right`}>Applications</th>
              <th scope="col" className={`${th} pl-2.5 text-right`}>Reached interview</th>
              <th scope="col" className={`${th} pl-2.5 text-right`}>Interview percent</th>
              <th scope="col" className={`${th} pl-2.5 text-right`}>Hires</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.source}>
                <th scope="row" className="border-t border-divider py-[9px] text-left text-[13px] font-normal text-strong">
                  {row.source}
                </th>
                <td className={`${td} text-strong`}>{row.applications}</td>
                <td className={`${td} text-strong`}>{row.reached_interview}</td>
                <td className={`${td} text-strong`}>
                  {row.applications > 0 ? Math.round((row.reached_interview / row.applications) * 100) : "-"}
                </td>
                <td className={`${td} ${row.hires === 0 ? "text-g500" : "text-strong"}`}>{row.hires}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
