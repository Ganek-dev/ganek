/** Where a candidate came from (spec job posts v2 5.4, decision JP2).
 *
 * Resolved once, server-side, in the request that renders a public page:
 * `src` query parameter (our tracked links), else `utm_source`, else the
 * inbound Referer origin mapped to a bucket, else "direct". The stored
 * grammar is mirrored and re-validated by `backend/app/core/sources.py`:
 * `direct`, a known bucket, `link:<name>`, `ref:<registrable domain>`.
 * Never a full URL, never a user agent, never an IP. */

export const KNOWN_SOURCES = [
  "direct",
  "google",
  "linkedin",
  "indeed",
  "facebook",
  "x",
  "glassdoor",
  "xing",
  "stepstone",
  "hn",
  "reddit",
  "github",
  "website",
] as const;

export type KnownSource = (typeof KNOWN_SOURCES)[number];

const KNOWN = new Set<string>(KNOWN_SOURCES);

/** registrable domain -> bucket; "google" also covers Google for Jobs */
const HOST_BUCKETS: Record<string, KnownSource> = {
  "linkedin.com": "linkedin",
  "lnkd.in": "linkedin",
  "facebook.com": "facebook",
  "fb.com": "facebook",
  "fb.me": "facebook",
  "x.com": "x",
  "twitter.com": "x",
  "t.co": "x",
  "xing.com": "xing",
  "ycombinator.com": "hn",
  "reddit.com": "reddit",
  "redd.it": "reddit",
  "github.com": "github",
};

/** brands that sit on many country TLDs: match the label before the suffix */
const BRAND_BUCKETS: Record<string, KnownSource> = {
  google: "google",
  indeed: "indeed",
  glassdoor: "glassdoor",
  stepstone: "stepstone",
};

/** second-level labels under which the real domain is one level deeper */
const SECOND_LEVEL = new Set(["co", "com", "org", "net", "gov", "ac", "edu"]);

const LINK_NAME = /^[a-z0-9_-]{1,40}$/;
const REF_HOST = /^(?=.{1,63}$)[a-z0-9-]+(?:\.[a-z0-9-]+)+$/;

export function registrableDomain(host: string): string {
  const labels = host.toLowerCase().split(".").filter(Boolean);
  if (labels.length <= 2) return labels.join(".");
  const take = SECOND_LEVEL.has(labels[labels.length - 2]!) ? 3 : 2;
  return labels.slice(-take).join(".");
}

function hostOf(referer: string): string | null {
  try {
    const url = new URL(referer);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.hostname.toLowerCase();
  } catch {
    return null;
  }
}

/** Bucket for an inbound Referer (origin is enough; the path is never read
 * beyond parsing). `websiteHost` is the company's own site, so arrivals
 * from it count as "website". Unknown hosts become `ref:<domain>`. */
export function bucketFromReferrer(referer: string | null, websiteHost: string | null): string {
  if (!referer) return "direct";
  const host = hostOf(referer);
  if (host === null || !host.includes(".") || /^[\d.]+$/.test(host)) return "direct";
  const domain = registrableDomain(host);
  if (websiteHost && registrableDomain(websiteHost) === domain) return "website";
  const known = HOST_BUCKETS[domain];
  if (known) return known;
  const brand = BRAND_BUCKETS[domain.split(".")[0]!];
  if (brand) return brand;
  return REF_HOST.test(domain) ? `ref:${domain}` : "direct";
}

/** `src` / `utm_source` value -> link name, or null when it is not one. */
export function normalizeLinkName(raw: string): string | null {
  const name = raw.trim().toLowerCase();
  return LINK_NAME.test(name) ? name : null;
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** A query value becomes a bucket when it names one, a stored `ref:` value
 * when it already is one, otherwise `link:<name>`; invalid -> null. */
function fromQuery(value: string | string[] | undefined): string | null {
  const raw = first(value);
  if (raw === undefined) return null;
  const lowered = raw.trim().toLowerCase();
  if (KNOWN.has(lowered)) return lowered;
  if (lowered.startsWith("ref:") && REF_HOST.test(lowered.slice(4))) return lowered;
  if (lowered.startsWith("link:")) {
    const name = normalizeLinkName(lowered.slice(5));
    return name ? `link:${name}` : null;
  }
  const name = normalizeLinkName(lowered);
  return name ? `link:${name}` : null;
}

export function resolveSource(input: {
  src?: string | string[];
  utm_source?: string | string[];
  referer: string | null;
  websiteHost: string | null;
}): string {
  return (
    fromQuery(input.src) ??
    fromQuery(input.utm_source) ??
    bucketFromReferrer(input.referer, input.websiteHost)
  );
}

/** Host of the company's website URL, for the "website" bucket. */
export function websiteHostOf(website: string | null | undefined): string | null {
  if (!website) return null;
  return hostOf(website.includes("://") ? website : `https://${website}`);
}

/** Query suffix a careers-list link carries so the job page keeps the
 * source across the same-origin hop (Referrer-Policy: no-referrer strips
 * the Referer there). Empty for direct arrivals: most URLs stay clean. */
export function sourceSuffix(source: string): string {
  return source === "direct" ? "" : `?src=${encodeURIComponent(source)}`;
}
