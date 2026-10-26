import type { ApplicationStage, QuizResult } from "@/lib/api";

/** Score tones, the score chip and the stage pill shared by the applicant
 * review list (screen 11) and the job overview's candidate table. */

export const SCORE_TONE = {
  green: {
    chip: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
    bar: "bg-emerald-200 dark:bg-emerald-900",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  amber: {
    chip: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
    bar: "bg-amber-200 dark:bg-amber-900",
    text: "text-amber-700 dark:text-amber-300",
  },
  red: {
    chip: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
    bar: "bg-red-200 dark:bg-red-900",
    text: "text-red-700 dark:text-red-400",
  },
  muted: {
    chip: "border-edge bg-muted-fill text-g500",
    bar: "bg-muted-fill",
    text: "text-g500",
  },
} as const;

export function toneFor(percent: number): keyof typeof SCORE_TONE {
  if (percent >= 60) return "green";
  if (percent >= 40) return "amber";
  return "red";
}

export function ScoreChip({ result }: { result: QuizResult | null }) {
  if (!result || result.status !== "completed" || result.score === null) {
    return (
      <span className={`inline-flex h-[22px] items-center rounded-full px-2 font-mono text-xs ${SCORE_TONE.muted.chip}`}>
        -
      </span>
    );
  }
  const percent = Math.round(result.score * 100);
  const tone = SCORE_TONE[toneFor(percent)];
  return (
    <span
      className={`inline-flex h-[22px] items-center rounded-full border px-2 font-mono text-xs font-semibold ${tone.chip}`}
    >
      {percent}
    </span>
  );
}

export function StagePill({ stage }: { stage: ApplicationStage }) {
  const cls =
    stage === "rejected"
      ? SCORE_TONE.red.chip
      : stage === "withdrawn"
        ? SCORE_TONE.muted.chip
      : stage === "hired" || stage === "offer"
        ? SCORE_TONE.green.chip
        : stage === "new"
          ? "border-accent/30 bg-accent/10 text-accent"
          : "border-edge bg-muted-fill text-g600";
  return (
    <span
      className={`inline-flex h-5 items-center rounded-full border px-2 text-[11px] font-medium ${cls}`}
    >
      {stage}
    </span>
  );
}
