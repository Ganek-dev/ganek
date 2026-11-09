import type { UserOut } from "@/lib/api";

/** Where a signed-in user lands: reviewers get their own reduced shell and
 * are 403 on everything under /admin, staff never see /review. */
export function homePath(user: Pick<UserOut, "role">): string {
  return user.role === "reviewer" ? "/review" : "/admin";
}

/** Where to go after sign-in when /login was opened with `?next=`: only a
 * team-invite page, so the link cannot send anyone off-site. */
export function safeNext(value: string | null): string | null {
  return value && /^\/invite\/[A-Za-z0-9._~-]+$/.test(value) ? value : null;
}
