import { NextResponse, type NextRequest } from "next/server";

/** Admin shell guard (M5.7 H4): no session cookie → straight to /login,
 * before any admin JS ships. Presence-only — the signature and
 * token_version are verified by the backend on every API call; this just
 * spares logged-out visitors the skeleton-then-redirect dance. */

export function middleware(request: NextRequest) {
  if (!request.cookies.has("vetd_session")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/admin/:path*",
};
