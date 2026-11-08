import { ApiError } from "@/lib/api";

/** The 402 a publish or reopen answers when the plan's live job limit is
 * reached (card B1b). Admins get the server's upgrade link; recruiters
 * cannot change the plan, so they are told to ask an admin (Q14). */
export interface PlanLimit {
  limit: number;
  upgradeUrl: string | null;
}

export function planLimitOf(err: unknown): PlanLimit | null {
  if (!(err instanceof ApiError) || err.status !== 402) return null;
  const body = err.body as { code?: unknown; limit?: unknown; upgrade_url?: unknown } | undefined;
  if (body?.code !== "plan_limit" || typeof body.limit !== "number") return null;
  return {
    limit: body.limit,
    upgradeUrl: typeof body.upgrade_url === "string" ? body.upgrade_url : null,
  };
}

export function planLimitMessage(limit: PlanLimit, isAdmin: boolean): string {
  const jobs = limit.limit === 1 ? "job" : "jobs";
  const next = isAdmin
    ? "Close a job or upgrade the plan to publish another."
    : "Close a job or ask your admin to upgrade the plan.";
  return `Your plan allows ${limit.limit} live ${jobs}. ${next}`;
}
