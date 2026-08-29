/** Canonical public origin for absolute URLs (sitemap, robots, OG metadata).
 * Mirrors the backend's GANEK_PUBLIC_BASE_URL (compose passes it to both). */
export function publicBaseUrl(): string {
  const raw = process.env.GANEK_PUBLIC_BASE_URL ?? "http://localhost:3000";
  return raw.replace(/\/+$/, "");
}
