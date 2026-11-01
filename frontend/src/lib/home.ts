import type { UserOut } from "@/lib/api";

/** Where a signed-in user lands: reviewers get their own reduced shell and
 * are 403 on everything under /admin, staff never see /review. */
export function homePath(user: Pick<UserOut, "role">): string {
  return user.role === "reviewer" ? "/review" : "/admin";
}
