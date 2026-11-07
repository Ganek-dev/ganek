import type { RemotePolicy } from "./api";

/** Location is free text and the remote policy is an enum, so the two can
 * contradict each other ("Berlin or remote (EU)" next to an "On-site" chip).
 * This spots the obvious cases so the job form can warn before publishing.
 * It is a hint only: saving stays allowed. */

// "no remote", "not remote", "non-remote" are consistent with on-site
const NEGATED = /\b(?:no|not|non)[\s-]+(?:remote|hybrid)\b/g;

const REMOTE_WORDS = /\b(?:remote|remotely|wfh|anywhere|distributed|telecommut\w*)\b|work(?:ing)? from home|home[\s-]?office/;
const HYBRID_WORDS = /\bhybrid\b/;
const ONSITE_WORDS = /\b(?:on[\s-]?site|in[\s-]office|office[\s-]based|in[\s-]person)\b/;

const LABELS: Record<RemotePolicy, string> = {
  onsite: "On-site",
  hybrid: "Hybrid",
  remote: "Remote",
};

function hint(word: string, policy: RemotePolicy): string {
  return `The location mentions ${word} work but the remote policy is ${LABELS[policy]}. Candidates see both, so pick the policy that matches or reword the location.`;
}

export function locationPolicyHint(location: string, policy: RemotePolicy): string | null {
  const text = location.toLowerCase().replace(NEGATED, " ");
  if (text.trim() === "") return null;
  if (policy === "onsite") {
    if (REMOTE_WORDS.test(text)) return hint("remote", policy);
    if (HYBRID_WORDS.test(text)) return hint("hybrid", policy);
  }
  if (policy === "remote") {
    if (ONSITE_WORDS.test(text)) return hint("on-site", policy);
    if (HYBRID_WORDS.test(text)) return hint("hybrid", policy);
  }
  return null;
}
