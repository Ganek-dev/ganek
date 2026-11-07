import type { PublicScreeningQuestion } from "@/lib/public-api";

/** One source of truth for the "N fields, about M minutes" apply copy, shown
 * in the job page's "How we hire" card and above the apply form. Both read
 * the same form config, so they can no longer drift apart. */

// a typed field (name, email, a short answer or a tick) takes about this long
const SECONDS_PER_FIELD = 30;
// picking a PDF from disk is slower than typing a line
const CV_EXTRA_SECONDS = 30;

const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];

function numberWord(n: number): string {
  return n >= 0 && n < WORDS.length ? WORDS[n] : String(n);
}

export interface ApplyFormShape {
  /** demo workspaces attach a sample CV, so there is no upload field */
  demo?: boolean;
  screeningQuestions?: Pick<PublicScreeningQuestion, "type" | "required">[];
}

/** Required fields a candidate fills: name, email, the CV (not on the demo)
 * and every required screening question (an acknowledgment is always
 * required). Optional links and the message are not counted. */
export function applyFieldCount({ demo = false, screeningQuestions = [] }: ApplyFormShape): number {
  const screening = screeningQuestions.filter(
    (q) => q.required || q.type === "acknowledgment",
  ).length;
  return 2 + (demo ? 0 : 1) + screening;
}

/** Whole minutes, rounded up, at least one. */
export function applyMinutes(shape: ApplyFormShape): number {
  const seconds =
    applyFieldCount(shape) * SECONDS_PER_FIELD + (shape.demo ? 0 : CV_EXTRA_SECONDS);
  return Math.max(1, Math.ceil(seconds / 60));
}

/** "three fields, about two minutes" (lower case, for use mid-sentence). */
export function applyEffort(shape: ApplyFormShape): string {
  const fields = applyFieldCount(shape);
  const minutes = applyMinutes(shape);
  return `${numberWord(fields)} ${fields === 1 ? "field" : "fields"}, about ${numberWord(minutes)} ${
    minutes === 1 ? "minute" : "minutes"
  }`;
}
