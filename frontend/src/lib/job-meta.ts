import { EMPLOYMENT_LABELS, REMOTE_LABELS, formatSalary } from "@/components/careers";

import type { PublicCompany, PublicJobDetail } from "./public-api";

/** Search snippets and share cards truncate past this; Google reads ~160. */
const MAX_LENGTH = 200;
/** em and en dashes, written as escapes: the house rule bans the glyphs in source */
const DASHES = new RegExp("[\\u2013\\u2014]", "g");

/** Plain text of the first real paragraph of a markdown body.
 *
 * Headings, code fences and blank lines are skipped; a list item counts as
 * a paragraph so a description that opens with bullets still yields a
 * sentence. Inline markup is stripped, not rendered.
 */
export function firstParagraphText(markdown: string): string {
  const blocks = markdown
    .replace(/```[\s\S]*?```/g, "")
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  for (const block of blocks) {
    if (/^#{1,6}\s/.test(block)) continue;
    const lines = block
      .split("\n")
      .map((line) => line.replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "").replace(/^>\s?/, "").trim())
      .filter(Boolean);
    if (lines.length === 0) continue;
    // the first list item alone: the whole list would read as one run-on
    const text = /^\s*(?:[-*+]|\d+[.)])\s+/.test(block) ? lines[0] : lines.join(" ");
    const plain = stripInline(text);
    if (plain) return plain;
  }
  return "";
}

function stripInline(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/(\*\*|__)(.*?)\1/g, "$2")
    .replace(/(\*|_)(.*?)\1/g, "$2")
    .replace(/<[^>]+>/g, "")
    .replace(DASHES, "-")
    .replace(/\s+/g, " ")
    .trim();
}

function cutAtWord(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 3);
  const atWord = cut.lastIndexOf(" ");
  return `${(atWord > 0 ? cut.slice(0, atWord) : cut).replace(/[\s.,;:]+$/, "")}...`;
}

/** Meta and og:description for a job page: the job, not the platform.
 *
 * First paragraph of the posting, then location, remote policy, type and
 * salary. Falls back to the company description when the posting carries
 * none of that, so a share card never advertises Ganek instead of the role.
 */
export function jobMetaDescription(
  job: PublicJobDetail,
  company: PublicCompany,
): string | undefined {
  const facts = [
    job.location || null,
    REMOTE_LABELS[job.remote_policy] ?? null,
    EMPLOYMENT_LABELS[job.employment_type] ?? null,
    formatSalary(job),
  ]
    .filter(Boolean)
    .join(" · ");
  const paragraph = firstParagraphText(job.description_md ?? "");
  if (!paragraph && !facts) return company.description || undefined;
  if (!paragraph) return facts;
  if (!facts) return cutAtWord(paragraph, MAX_LENGTH);
  const room = MAX_LENGTH - facts.length - 1;
  const lead = cutAtWord(paragraph, room);
  const ended = /[.!?…]$/.test(lead) || lead.endsWith("...") ? lead : `${lead}.`;
  return `${ended} ${facts}`;
}
