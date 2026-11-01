import { type Scorecard } from "@/lib/api";

/** Read-only scorecard pieces shared by the candidate panel (ScorecardsCard)
 * and the reviewer page. The recommendation chip is deliberately neutral
 * (no red/green scoring). */

function initials(label: string): string {
  const parts = label.split(/[\s@.]+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}

export function Avatar({ label }: { label: string }) {
  return (
    <span
      aria-hidden
      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted-fill font-mono text-[10px] font-medium text-g600"
    >
      {initials(label)}
    </span>
  );
}

export function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex h-5 items-center rounded-full border border-edge bg-muted-fill px-2 text-[11px] font-medium text-g600">
      {children}
    </span>
  );
}

function Dots({ value }: { value: number | undefined }) {
  if (value === undefined) return <span className="text-[11.5px] text-g500">Not assessed</span>;
  return (
    <span className="inline-flex items-center gap-1" role="img" aria-label={`${value} of 4`}>
      {[1, 2, 3, 4].map((n) => (
        <span
          key={n}
          aria-hidden
          className={`h-2 w-2 rounded-full ${n <= value ? "bg-inverse" : "border border-edge"}`}
        />
      ))}
    </span>
  );
}

export function SubmittedBody({ row }: { row: Scorecard }) {
  return (
    <div className="mt-2 space-y-2">
      <ul className="space-y-1">
        {row.criteria.map((criterion) => (
          <li key={criterion.id} className="flex items-center justify-between gap-3">
            <span className="text-[12.5px]">{criterion.label}</span>
            <Dots value={row.ratings[criterion.id]} />
          </li>
        ))}
      </ul>
      {row.comment ? <p className="text-[13px] leading-[19px]">{row.comment}</p> : null}
    </div>
  );
}
