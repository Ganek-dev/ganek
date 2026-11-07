import { NextResponse, type NextRequest } from "next/server";

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
 * view. */
async function jobStatus(request: NextRequest, lookup: string): Promise<NextResponse> {
  if (request.nextUrl.searchParams.has("preview")) return NextResponse.next();
  // client-side navigations and prefetches fetch the RSC payload: the status
  // only matters to document loads (crawlers), and a 404 there would turn a
  // soft navigation into a hard reload
  if (request.headers.has("rsc") || request.headers.has("next-router-prefetch")) {
    return NextResponse.next();
  }
  try {
    const resp = await fetch(`${BACKEND_URL}${lookup}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (resp.status === 404) return NextResponse.rewrite(request.nextUrl, { status: 404 });
  } catch {
    // fail open
  }
  return NextResponse.next();
}

/** Admin and reviewer shell guard (M5.7 H4): no session cookie -> straight to /login,
 * before any admin JS ships. Presence-only - the signature and
 * token_version are verified by the backend on every API call; this just
 * spares logged-out visitors the skeleton-then-redirect dance. */
export async function middleware(request: NextRequest): Promise<NextResponse> {
  const lookup = jobLookupPath(request.nextUrl.pathname);
  if (lookup !== null) return jobStatus(request, lookup);
  if (!request.cookies.has("ganek_session")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/admin/:path*", "/review/:path*", "/jobs/:jobSlug", "/c/:slug/jobs/:jobSlug"],
};
