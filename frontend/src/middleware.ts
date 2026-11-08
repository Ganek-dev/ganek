import { NextResponse, type NextRequest } from "next/server";

import { publicBaseUrl } from "@/lib/site";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

/** Public job pages: the backend lookup that decides a real 404.
 * `/jobs/<job>` (single mode) and `/c/<company>/jobs/<job>` (multi mode).
 * Returns null for any other path. */
export function jobLookupPath(pathname: string): string | null {
  const single = /^\/jobs\/([^/]+)\/?$/.exec(pathname);
  if (single) return `/api/v1/public/company/jobs/${single[1]}`;
  const multi = /^\/c\/([^/]+)\/jobs\/([^/]+)\/?$/.exec(pathname);
  if (multi) return `/api/v1/public/companies/${multi[1]}/jobs/${multi[2]}`;
  return null;
}

/** Unknown or closed job: the page still renders its themed "job gone" or
 * global not-found screen, but with a real 404 status. The root loading.tsx
 * makes every page stream, and a streamed response is already a 200 by the
 * time the page could call notFound(), so the status has to be decided here,
 * before rendering (soft 404s are bad for crawlers and Google Jobs). Preview
 * links skip the check (the token lookup belongs to the page, and previews
 * are noindex anyway). Any backend hiccup fails open: the page renders as
 * before. The lookup never carries the view headers, so it never counts a
 * view. `target` is the internal route a custom domain path was rewritten
 * to (null: the request path itself). */
async function jobStatus(
  request: NextRequest,
  lookup: string,
  target: URL | null = null,
): Promise<NextResponse> {
  const pass = () => (target ? NextResponse.rewrite(target) : NextResponse.next());
  if (request.nextUrl.searchParams.has("preview")) return pass();
  // client-side navigations and prefetches fetch the RSC payload: the status
  // only matters to document loads (crawlers), and a 404 there would turn a
  // soft navigation into a hard reload
  if (request.headers.has("rsc") || request.headers.has("next-router-prefetch")) {
    return pass();
  }
  try {
    const resp = await fetch(`${BACKEND_URL}${lookup}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (resp.status === 404) {
      return NextResponse.rewrite(target ?? request.nextUrl, { status: 404 });
    }
  } catch {
    // fail open
  }
  return pass();
}

/** A Host header as the backend compares it: lowercase, no port, no
 * trailing dot. Empty for a missing header. */
export function normalizeHost(raw: string | null): string {
  if (!raw) return "";
  let host = raw.trim().toLowerCase();
  if (host.startsWith("[")) return host; // IPv6 literal, never a custom domain
  host = host.replace(/:\d+$/, "");
  return host.replace(/\.+$/, "");
}

/** Hosts that can never be a tenant's custom domain, so the middleware
 * never asks the backend about them: the instance's own host, localhost
 * and IP literals (health checks, internal calls). */
export function isInstanceHost(host: string): boolean {
  if (!host || host === "localhost" || host.endsWith(".localhost")) return true;
  if (host.startsWith("[") || /^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return true;
  // a name without a dot is a container or LAN name, not a public domain
  if (!host.includes(".")) return true;
  let instance = "";
  try {
    instance = new URL(publicBaseUrl()).hostname.toLowerCase().replace(/\.+$/, "");
  } catch {
    // a malformed base URL: treat no host as the instance's
  }
  return host === instance;
}

const RESOLVE_TTL_MS = 60_000;
const RESOLVE_CACHE_MAX = 1000;
const resolveCache = new Map<string, { slug: string | null; expires: number }>();

/** Test hook: forget every cached Host resolution. */
export function clearDomainCache(): void {
  resolveCache.clear();
}

/** The company slug a verified custom domain belongs to, or null. Answers
 * (hit and miss) are cached per host for a minute so a busy careers page
 * costs one backend lookup a minute, not one per request; a domain removed
 * or downgraded stops routing within that minute. Backend errors are not
 * cached and fail open (the request is served as on the instance host). */
async function customDomainSlug(host: string): Promise<string | null> {
  const now = Date.now();
  const hit = resolveCache.get(host);
  if (hit && hit.expires > now) return hit.slug;
  let slug: string | null;
  try {
    const resp = await fetch(
      `${BACKEND_URL}/api/v1/public/domains/resolve?host=${encodeURIComponent(host)}`,
      { cache: "no-store", headers: { Accept: "application/json" } },
    );
    if (resp.status === 404) {
      slug = null;
    } else if (resp.ok) {
      const body = (await resp.json()) as { slug?: unknown };
      slug = typeof body.slug === "string" && body.slug ? body.slug : null;
    } else {
      return null;
    }
  } catch {
    return null;
  }
  if (resolveCache.size >= RESOLVE_CACHE_MAX) resolveCache.clear();
  resolveCache.set(host, { slug, expires: now + RESOLVE_TTL_MS });
  return slug;
}

/** Signed-in surfaces stay on the instance host: a custom domain only
 * serves the careers site (session cookies are never set on it). */
const ADMIN_PATH = /^\/(admin|review|login|setup)(\/|$)/;

/** Where a path on company `slug`'s custom domain is served from:
 * - `{rewrite}`: the careers route behind it (`/` -> `/c/{slug}`,
 *   `/jobs/<job>` -> `/c/{slug}/jobs/<job>`, `/privacy` -> `/c/{slug}/privacy`);
 * - `{notFound}`: another tenant's `/c/<other>` pages, which a tenant's own
 *   domain must never show;
 * - `{admin}`: a signed-in surface, sent to the instance host;
 * - `{pass}`: everything else (the tenant's own `/c/{slug}` links, the
 *   capability-token pages such as quiz and application status). */
export type CustomDomainRoute =
  | { rewrite: string }
  | { notFound: true }
  | { admin: true }
  | { pass: true };

export function customDomainRoute(pathname: string, slug: string): CustomDomainRoute {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (path === "/") return { rewrite: `/c/${slug}` };
  if (path === "/privacy") return { rewrite: `/c/${slug}/privacy` };
  const job = /^\/jobs\/([^/]+)$/.exec(path);
  if (job) return { rewrite: `/c/${slug}/jobs/${job[1]}` };
  const tenant = /^\/c\/([^/]+)(\/|$)/.exec(path);
  if (tenant) return tenant[1] === slug ? { pass: true } : { notFound: true };
  if (ADMIN_PATH.test(path)) return { admin: true };
  return { pass: true };
}

async function customDomain(request: NextRequest, slug: string): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;
  const route = customDomainRoute(pathname, slug);
  if ("notFound" in route) {
    return new NextResponse("Not found", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  if ("admin" in route) {
    return NextResponse.redirect(`${publicBaseUrl()}${pathname}${search}`);
  }
  if ("pass" in route) {
    const lookup = jobLookupPath(pathname);
    return lookup !== null ? jobStatus(request, lookup) : NextResponse.next();
  }
  const target = request.nextUrl.clone();
  target.pathname = route.rewrite;
  const lookup = jobLookupPath(route.rewrite);
  return lookup !== null ? jobStatus(request, lookup, target) : NextResponse.rewrite(target);
}

/** 1. A verified custom domain (card C1) serves its tenant's careers site
 * at the domain root. 2. Public job pages get a real 404 status.
 * 3. Admin and reviewer shell guard (M5.7 H4): no session cookie ->
 * straight to /login, before any admin JS ships. Presence-only - the
 * signature and token_version are verified by the backend on every API
 * call; this just spares logged-out visitors the skeleton-then-redirect
 * dance. */
export async function middleware(request: NextRequest): Promise<NextResponse> {
  const host = normalizeHost(request.headers.get("host"));
  if (!isInstanceHost(host)) {
    const slug = await customDomainSlug(host);
    if (slug !== null) return customDomain(request, slug);
  }
  const { pathname } = request.nextUrl;
  const lookup = jobLookupPath(pathname);
  if (lookup !== null) return jobStatus(request, lookup);
  if (/^\/(admin|review)(\/|$)/.test(pathname) && !request.cookies.has("ganek_session")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/",
    "/privacy",
    "/login",
    "/setup",
    "/admin/:path*",
    "/review/:path*",
    "/jobs/:jobSlug",
    "/c/:path*",
  ],
};
