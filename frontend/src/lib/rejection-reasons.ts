/** The fixed list of internal rejection reasons (card "Candidate emails",
 * PR 2). Mirrors backend `app/services/rejection_reasons.py`: keys are what
 * the API stores, labels are what the team reads. Internal only: never
 * shown on a candidate page, never placed in an email. */

export type RejectionReason =
  | "another_candidate"
  | "skills_gap"
  | "salary_mismatch"
  | "location_or_permit"
  | "no_response"
  | "withdrew"
  | "other";

export const REJECTION_REASONS: { key: RejectionReason; label: string }[] = [
  { key: "another_candidate", label: "Another candidate preferred" },
  { key: "skills_gap", label: "Skills below the bar" },
  { key: "salary_mismatch", label: "Salary expectations did not match" },
  { key: "location_or_permit", label: "Location or work permit" },
  { key: "no_response", label: "No response from the candidate" },
  { key: "withdrew", label: "Candidate withdrew" },
  { key: "other", label: "Other" },
];

/** The label for a stored key; null for a missing or unknown value. */
export function reasonLabel(key: unknown): string | null {
  if (typeof key !== "string") return null;
  return REJECTION_REASONS.find((reason) => reason.key === key)?.label ?? null;
}
