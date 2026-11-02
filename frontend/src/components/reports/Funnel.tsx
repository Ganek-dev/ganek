import { ArrowDown } from "lucide-react";

import type { ReactNode } from "react";

import type { ApplicationStage, FunnelStep, QuizLine } from "@/lib/api";

/** Cohort funnel: one bar per step on a shared scale (steps[0] is the full
 * width), the pass-through percent between rows, and a split bar saying where
 * the rest went. The split bar uses the same pixels per candidate as the
 * funnel bar, and every count is printed beside it because the "still here"
 * fill is low contrast on purpose. */

const LABEL: Partial<Record<ApplicationStage, string>> = {
  new: "Applied",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
};

const label = (stage: ApplicationStage) => LABEL[stage] ?? stage;
const percent = (value: number | null) => (value === null ? null : `${Math.round(value)} percent`);

// bar column width: --funnel-w, 480px wide, narrower on small screens
const COLUMNS = "grid-cols-[84px_48px_var(--funnel-w)_minmax(0,200px)_64px_80px_64px]";

function Count({ value }: { value: number }) {
  return (
    <span className={`text-right font-mono text-[12.5px] ${value === 0 ? "text-g500" : "text-strong"}`}>
      {value}
    </span>
  );
}

function Swatch({ token }: { token: string }) {
  return (
    <span
      aria-hidden
      className="inline-block h-2 w-2 shrink-0 rounded-[2px]"
      style={{ background: `var(${token})` }}
    />
  );
}

const SEGMENTS = [
  { key: "rejected_from", token: "--split-rejected" },
  { key: "withdrawn_from", token: "--split-withdrawn" },
  { key: "still_here", token: "--split-still" },
] as const;

export function Funnel({
  steps,
  quiz,
  children,
}: {
  steps: FunnelStep[];
  quiz: QuizLine;
  /** the diagnosis callout sits inside the card, under the quiz line */
  children?: ReactNode;
}) {
  const first = steps[0]?.reached ?? 0;
  const share = (n: number) => (first > 0 ? n / first : 0);
  const chartLabel = `Funnel: ${steps
    .map((s) => {
      const pass = percent(s.pass_through);
      return `${label(s.stage)} ${s.reached}${pass ? `, ${pass} move on` : ""}`;
    })
    .join("; ")}`;
  const quizPct = quiz.invited > 0 ? `${Math.round((quiz.completed / quiz.invited) * 100)} percent` : "-";

  return (
    <section className="card px-5 py-[18px]">
      <div className="flex items-baseline justify-between">
        <h2 className="font-heading text-[15px] font-semibold">Funnel</h2>
        <span className="font-mono text-[11px] text-g500">{first} applications</span>
      </div>
      <div role="img" aria-label={chartLabel}>
        <div
          data-testid="funnel-wide"
          className="hidden [--funnel-w:320px] min-[1400px]:[--funnel-w:480px] xl:block"
        >
          <div className={`mt-3.5 grid ${COLUMNS} gap-x-2.5 pb-2 text-[11px] text-g500`}>
            <span>Stage</span>
            <span className="text-right">Reached</span>
            <span />
            <span>Where the rest went</span>
            <span className="flex items-center justify-end gap-1">
              <Swatch token="--split-rejected" />
              rejected
            </span>
            <span className="flex items-center justify-end gap-1">
              <Swatch token="--split-withdrawn" />
              withdrawn
            </span>
            <span className="flex items-center justify-end gap-1">
              <Swatch token="--split-still" />
              still here
            </span>
          </div>
          <div>
            {steps.map((step, index) => {
              const last = index === steps.length - 1;
              const pass = percent(step.pass_through);
              const segments = SEGMENTS.filter((s) => step[s.key] > 0);
              return (
                <div key={step.stage}>
                  <div data-row className={`grid ${COLUMNS} min-h-[22px] items-center gap-x-2.5`}>
                    <span className="text-[13px] font-medium text-strong">{label(step.stage)}</span>
                    <span className="text-right font-mono text-[13px] font-medium text-strong">
                      {step.reached}
                    </span>
                    <div
                      data-testid="funnel-bar"
                      className="h-5 rounded-r-[4px]"
                      style={{
                        width: `calc(var(--funnel-w) * ${share(step.reached)})`,
                        background: "var(--chart-accent)",
                      }}
                    />
                    {last ? (
                      <span />
                    ) : (
                      <div className="flex h-3 gap-[2px]">
                        {segments.map((segment, i) => (
                          <div
                            key={segment.key}
                            data-testid="split-segment"
                            title={String(step[segment.key])}
                            className={i === segments.length - 1 ? "rounded-r-[3px]" : ""}
                            style={{
                              width: `calc(var(--funnel-w) * ${share(step[segment.key])})`,
                              background: `var(${segment.token})`,
                            }}
                          />
                        ))}
                      </div>
                    )}
                    {last ? (
                      <>
                        <span className="text-right text-[11px] text-g500">-</span>
                        <span className="text-right text-[11px] text-g500">-</span>
                        <span className="text-right text-[11px] text-g500">-</span>
                      </>
                    ) : (
                      <>
                        <Count value={step.rejected_from} />
                        <Count value={step.withdrawn_from} />
                        <Count value={step.still_here} />
                      </>
                    )}
                  </div>
                  {last ? null : (
                    <div className={`grid ${COLUMNS} h-5 items-center gap-x-2.5`}>
                      <span />
                      <span />
                      <span className="inline-flex items-center gap-1 text-[11px] text-g600">
                        <ArrowDown aria-hidden className="h-3 w-3 shrink-0" />
                        {pass}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <div data-testid="funnel-stacked" className="mt-3.5 space-y-3.5 xl:hidden">
          {steps.map((step, index) => {
            const last = index === steps.length - 1;
            const pass = percent(step.pass_through);
            const segments = SEGMENTS.filter((s) => step[s.key] > 0);
            return (
              <div key={step.stage}>
                <div className="flex items-baseline justify-between">
                  <span className="text-[13px] font-medium text-strong">{label(step.stage)}</span>
                  <span className="font-mono text-[13px] font-medium text-strong">{step.reached}</span>
                </div>
                <div className="mt-1">
                  <div
                    data-testid="funnel-bar-stacked"
                    className="h-5 rounded-r-[4px]"
                    style={{ width: `${share(step.reached) * 100}%`, background: "var(--chart-accent)" }}
                  />
                </div>
                {last ? null : (
                  <>
                    <div className="mt-1.5 flex h-2 gap-[2px]">
                      {segments.map((segment, i) => (
                        <div
                          key={segment.key}
                          data-testid="split-segment-stacked"
                          title={String(step[segment.key])}
                          className={i === segments.length - 1 ? "rounded-r-[3px]" : ""}
                          style={{
                            width: `${share(step[segment.key]) * 100}%`,
                            background: `var(${segment.token})`,
                          }}
                        />
                      ))}
                    </div>
                    <p data-testid="split-counts" className="mt-1 text-[11px] text-g500">
                      {`${step.rejected_from} rejected · ${step.withdrawn_from} withdrawn · ${step.still_here} still here`}
                    </p>
                    <span className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-g600">
                      <ArrowDown aria-hidden className="h-3 w-3 shrink-0" />
                      {pass}
                    </span>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <p className="mt-3 text-[11.5px] leading-[17px] text-g600">
        {`Quiz: ${quiz.invited} invited, ${quiz.completed} completed (${quizPct}), ${quiz.expired} expired`}
      </p>
      {children ? <div className="mt-3.5">{children}</div> : null}
      <details className="mt-2.5">
        <summary className="cursor-pointer text-[11px] text-accent-text">View as table</summary>
        <table className="mt-2 w-full border-collapse text-[11.5px] text-g600">
          <thead>
            <tr className="text-g500">
              {["Stage", "Reached", "Move on", "Rejected", "Withdrawn", "Still here"].map((h, i) => (
                <th key={h} scope="col" className={`py-0.5 font-normal ${i === 0 ? "text-left" : "text-right"}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {steps.map((step, index) => {
              const last = index === steps.length - 1;
              return (
                <tr key={step.stage} className="border-t border-divider">
                  <th scope="row" className="py-0.5 text-left font-normal">
                    {label(step.stage)}
                  </th>
                  <td className="py-0.5 text-right">{step.reached}</td>
                  <td className="py-0.5 text-right">{percent(step.pass_through) ?? "-"}</td>
                  <td className="py-0.5 text-right">{last ? "-" : step.rejected_from}</td>
                  <td className="py-0.5 text-right">{last ? "-" : step.withdrawn_from}</td>
                  <td className="py-0.5 text-right">{last ? "-" : step.still_here}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </details>
    </section>
  );
}
