/** What each email placeholder means, for the template editor's chips
 * (card "Candidate emails", PR 3). Mirrors the backend `PLACEHOLDERS`
 * names; the computed phrases list their possible values so a template
 * can keep today's conditional copy without conditionals. */

export const PLACEHOLDER_HELP: Record<string, { label: string; example: string }> = {
  candidate_name: { label: "Candidate name", example: "Alex Example" },
  candidate_first_name: { label: "Candidate first name", example: "Alex" },
  job_title: { label: "Job title", example: "Backend Engineer" },
  company_name: { label: "Company name", example: "your workspace name" },
  question_count: { label: "Question count", example: "8" },
  time_per_question: { label: "Time per question", example: "25s" },
  valid_until: { label: "Valid until", example: "Thu, Nov 6" },
  days_left: { label: "Days left", example: "3" },
  expires_phrase: { label: "Expires phrase", example: "today / in 1 day / in 3 days" },
  days_left_phrase: { label: "Days left phrase", example: "last day / 1 day left / 3 days left" },
  assessment_thanks: {
    label: "Assessment thanks",
    example: "the thank-you sentence when the candidate completed the assessment, else empty",
  },
};

export function placeholderHelp(name: string): { label: string; example: string } {
  return PLACEHOLDER_HELP[name] ?? { label: name, example: "" };
}
