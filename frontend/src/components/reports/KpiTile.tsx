import { ArrowDown, ArrowUp } from "lucide-react";

/** Signed change versus the previous period. Neutral on purpose: a rise in
 * rejections or in time to hire is not "bad" by itself, so it never takes a
 * good or bad colour. Null (no previous period) draws nothing. */
export function DeltaText({ value, unit = "" }: { value: number | null; unit?: string }) {
  if (value === null) return null;
  const Icon = value > 0 ? ArrowUp : value < 0 ? ArrowDown : null;
  const text = `${value > 0 ? "+" : ""}${value}${unit}`;
  return (
    <span className="inline-flex items-center gap-[3px] font-mono text-[11px] text-g600">
      {Icon ? <Icon aria-hidden className="h-3 w-3 shrink-0" /> : null}
      {text}
    </span>
  );
}

export function KpiTile({
  label,
  value,
  unit,
  delta,
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  /** undefined or null: no delta */
  delta?: number | null;
  note?: string;
}) {
  const hasDelta = delta !== undefined && delta !== null;
  return (
    <div className="card min-w-0 px-4 py-3.5">
      <p className="text-xs text-g500">{label}</p>
      <p className="mt-1.5 font-heading text-[26px] leading-none font-semibold text-strong">
        {value}
        {unit ? <span className="text-[15px] font-medium text-g500"> {unit}</span> : null}
      </p>
      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] leading-[15px] text-g500">
        {hasDelta ? (
          <>
            <DeltaText value={delta} />
            <span className="font-mono">vs previous</span>
          </>
        ) : null}
        {note ? <span className="font-mono whitespace-nowrap">{note}</span> : null}
      </p>
    </div>
  );
}
