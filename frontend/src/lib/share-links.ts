/** Tracked share links (spec job posts v2 5.2 item 5). A `?src=<name>`
 * suffix on the public job URL is the whole mechanism: the job page's source
 * resolver (`lib/source.ts`) turns it into a bucket or `link:<name>`, the
 * view counter and the apply form carry that label, and the overview's
 * Sources table lists it. No storage, no shortener, no click tracking. */

import { resolveSource } from "@/lib/source";

export const SHARE_PRESETS: readonly { name: string; label: string }[] = [
  { name: "linkedin", label: "LinkedIn" },
  { name: "indeed", label: "Indeed" },
  { name: "x", label: "X" },
  { name: "newsletter", label: "Newsletter" },
];

export const EMBED_DOCS_URL = "https://ganek.dev/api-embed/";

export const CUSTOM_NAME_HINT = "letters, digits, - or _ only, up to 40";

/** The job URL with `src=<name>` in its query: set, not appended, so an
 * existing `src` is replaced and a fragment stays at the end. */
export function shareUrl(jobUrl: string, name: string): string {
  const url = new URL(jobUrl);
  url.searchParams.set("src", name);
  return url.toString();
}

/** What to tell a recruiter whose custom name is already a built-in source
 * label (a known bucket or one of its utm aliases). `direct` is the name of
 * untracked traffic, so a link called that could never be told apart from
 * it: the card withholds the link. Any other bucket is honest and useful. */
export function builtInSourceHint(label: string): string {
  if (label === "direct") {
    return "direct is the built-in name for untracked traffic, so a link called direct could not be told apart from it. Pick another name.";
  }
  return `already a built-in source, appears as ${label} in Sources`;
}

/** The label the Sources table will show for this name: asked of the same
 * resolver the job page runs on `?src=`, so the two can never disagree
 * (known buckets and utm aliases included). */
export function sourceLabelFor(name: string): string {
  return resolveSource({ src: name, referer: null, websiteHost: null });
}
