export type InstanceMode = "single" | "multi";

/** Canonical URL of a careers page, or of one job when ``jobSlug`` is
 * given, from the server's ``careers_url`` (the custom domain once
 * verified). null when the backend did not send one. */
export function canonicalCareersUrl(
  company: { careers_url?: string | null },
  jobSlug?: string,
): string | null {
  const base = company.careers_url?.replace(/\/+$/, "");
  if (!base) return null;
  return jobSlug ? `${base}/jobs/${encodeURIComponent(jobSlug)}` : base;
}

/** Next metadata ``alternates.canonical`` for a careers page, or nothing. */
export function canonicalMetadata(
  company: { careers_url?: string | null },
  jobSlug?: string,
): { alternates?: { canonical: string } } {
  const url = canonicalCareersUrl(company, jobSlug);
  return url ? { alternates: { canonical: url } } : {};
}

/** The careers-page URL this deployment actually serves - single mode at the
 * instance root, multi mode under /c/{slug}, the root of the verified custom
 * domain when the server sends ``domain`` (``careers_domain``). Never a
 * ganek.dev domain: those don't exist for self-hosted instances. Origin
 * resolves in the browser; the callers are client components that render
 * after data fetches. */
export function careersUrl(mode: InstanceMode, slug: string, domain?: string | null): string {
  if (domain) return `https://${domain}`;
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return mode === "single" ? origin : `${origin}/c/${slug}`;
}

/** Protocol-less form for mono labels next to a Copy button. */
export function careersDisplay(mode: InstanceMode, slug: string, domain?: string | null): string {
  return careersUrl(mode, slug, domain).replace(/^https?:\/\//, "");
}

/** Slug-bearing preview for the setup form, before a company exists. The
 * /c/{slug} route resolves in both modes, and keeping the slug visible is
 * the point of the live preview - the canonical share URL (host in single
 * mode) is what the checklist and branding surfaces show instead. */
export function careersSlugPreview(slug: string): string {
  return careersDisplay("multi", slug);
}
