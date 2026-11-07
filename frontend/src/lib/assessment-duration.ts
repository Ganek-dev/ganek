/** How long an assessment takes, from the two numbers the server freezes on
 * the attempt: question count x seconds per question, rounded up to whole
 * minutes (at least 1). Mirrors the backend `assessment_duration` so the
 * success panel, the invite and the reminder print one figure. Null seconds
 * means each question keeps its own limit: no number is promised. */

export function assessmentMinutes(
  questionCount: number | null | undefined,
  secondsPerQuestion: number | null | undefined,
): number | null {
  if (!questionCount || secondsPerQuestion === null || secondsPerQuestion === undefined) {
    return null;
  }
  return Math.max(1, Math.ceil((questionCount * secondsPerQuestion) / 60));
}

export function assessmentDuration(
  questionCount: number | null | undefined,
  secondsPerQuestion: number | null | undefined,
): string {
  const minutes = assessmentMinutes(questionCount, secondsPerQuestion);
  if (minutes === null) return "a few minutes";
  return `about ${minutes} minute${minutes === 1 ? "" : "s"}`;
}
