/** Tracked share links (spec job posts v2 5.2 item 5). A `?src=<name>`
 * suffix on the public job URL is the whole mechanism: the job page's source
 * resolver (`lib/source.ts`) turns it into a bucket or `link:<name>`, the
 * view counter and the apply form carry that label, and the overview's
 * Sources table lists it. No storage, no shortener, no click tracking. */

import { normalizeLinkName, resolveSource } from "@/lib/source";

export const SHARE_PRESETS: readonly { name: string; label: string }[] = [
  { name: "linkedin", label: "LinkedIn" },
  { name: "indeed", label: "Indeed" },
  { name: "x", label: "X" },
  { name: "newsletter", label: "Newsletter" },
];

export const EMBED_DOCS_URL = "https://ganek.dev/api-embed/";

export const CUSTOM_NAME_HINT = "letters, digits, - or _ only, up to 40";

export function shareUrl(jobUrl: string, name: string): string {
  const joiner = jobUrl.includes("?") ? "&" : "?";
  return `${jobUrl}${joiner}src=${encodeURIComponent(name)}`;
}

/** A name a recruiter typed, in the grammar the page accepts; null when the
 * page would drop it (the UI then shows CUSTOM_NAME_HINT). */
export function customShareName(raw: string): string | null {
  return normalizeLinkName(raw);
}

/** The label the Sources table will show for this name: asked of the same
 * resolver the job page runs on `?src=`, so the two can never disagree
 * (known buckets and utm aliases included). */
export function sourceLabelFor(name: string): string {
  return resolveSource({ src: name, referer: null, websiteHost: null });
}
