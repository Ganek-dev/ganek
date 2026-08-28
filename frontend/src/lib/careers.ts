export type InstanceMode = "single" | "multi";

/** The careers-page URL this deployment actually serves — single mode at the
 * instance root, multi mode under /c/{slug}. Never a ganek.dev domain: those
 * don't exist for self-hosted instances. Origin resolves in the browser; the
 * callers are client components that render after data fetches. */
export function careersUrl(mode: InstanceMode, slug: string): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return mode === "single" ? origin : `${origin}/c/${slug}`;
}

/** Protocol-less form for mono labels next to a Copy button. */
export function careersDisplay(mode: InstanceMode, slug: string): string {
  return careersUrl(mode, slug).replace(/^https?:\/\//, "");
}

/** Slug-bearing preview for the setup form, before a company exists. The
 * /c/{slug} route resolves in both modes, and keeping the slug visible is
 * the point of the live preview — the canonical share URL (host in single
 * mode) is what the checklist and branding surfaces show instead. */
export function careersSlugPreview(slug: string): string {
  return careersDisplay("multi", slug);
}
