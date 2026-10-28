/** Candidate-facing progress line for a finished assessment.
 *
 * Only locked answers count as answered; a question whose deadline passed
 * is listed separately so the count matches what the hiring team sees.
 */
export function answeredSummary(progress: {
  answered: number;
  timed_out: number;
  total: number;
}): string {
  if (progress.timed_out > 0) {
    return `${progress.answered} answered, ${progress.timed_out} timed out`;
  }
  return `${progress.answered} of ${progress.total} answered`;
}
