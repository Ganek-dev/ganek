/** Is this public job page load a countable view? (spec job posts v2 5.5)
 *
 * Decided in the server render from its own request, never stored: the
 * backend only ever receives two headers, "this load counts" and the source
 * bucket. Not counted: a signed-in recruiter (session cookie present on
 * this domain), a preview link, a router prefetch, a missing or bot-like
 * user agent. Pure module so the matcher is unit-testable; the e2e stack
 * has no bots. */

/** "bot" counts only where crawlers put it: before a version (`Googlebot/2.1`),
 * a separator (`PetalBot;`, `TwitterBot)`), a hyphen (`AdsBot-Google`,
 * `Slackbot-LinkExpanding`), a comma or the end of the string. A phone brand
 * such as CUBOT ("CUBOT X30 Build/...") has a space after it and stays a
 * person. "crawl" and "spider" stay substrings: `Baiduspider` and
 * `Bytespider` carry no boundary before them and no device name has them. */
export const BOT_UA =
  /bot(?:[/;)\-,]|$)|crawl|spider|slurp|facebookexternalhit|headless|preview|lighthouse/i;

export interface ViewSignals {
  userAgent: string | null;
  /** the admin session cookie rode along: the recruiter looking at their own page */
  hasSession: boolean;
  /** `?preview=` value when present (any value, valid or not) */
  preview: string | undefined;
  prefetch: boolean;
}

export function isBotUserAgent(ua: string | null): boolean {
  if (!ua) return true;
  return BOT_UA.test(ua);
}

/** Link hover prefetches must not render a view; Next sends
 * `Next-Router-Prefetch`, browsers `Purpose` / `Sec-Purpose: prefetch`. */
export function isPrefetch(h: { get(name: string): string | null }): boolean {
  if (h.get("next-router-prefetch") !== null) return true;
  const purpose = `${h.get("purpose") ?? ""} ${h.get("sec-purpose") ?? ""}`;
  return /prefetch/i.test(purpose);
}

export function shouldCountView(s: ViewSignals): boolean {
  if (s.hasSession || s.prefetch) return false;
  if (s.preview !== undefined && s.preview !== "") return false;
  return !isBotUserAgent(s.userAgent);
}

export function viewHeaders(source: string): Record<string, string> {
  return { "X-Ganek-View": "1", "X-Ganek-Source": source };
}
