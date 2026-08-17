/** Canonical public origin for absolute URLs (sitemap, robots, OG metadata).
 * Mirrors the backend's VETD_PUBLIC_BASE_URL (compose passes it to both). */
export function publicBaseUrl(): string {
  const raw = process.env.VETD_PUBLIC_BASE_URL ?? "http://localhost:3000";
  return raw.replace(/\/+$/, "");
}
