"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { type PlanLimit, planLimitMessage } from "@/lib/plan-limit";

/** Inline notice for a publish or reopen refused by the plan (402, card
 * B1b). Only an admin can change the plan, so only an admin sees the
 * upgrade link; everyone else is pointed at their admin. */
export function PlanLimitNotice({ limit }: { limit: PlanLimit }) {
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((user) => {
        if (!cancelled) setIsAdmin(user.role === "admin");
      })
      .catch(() => {
        // unknown role: the recruiter wording is safe for anyone
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <p
      role="alert"
      data-testid="plan-limit-notice"
      className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[13px] text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200"
    >
      {planLimitMessage(limit, isAdmin)}
      {isAdmin && limit.upgradeUrl ? (
        <>
          {" "}
          <a href={limit.upgradeUrl} className="font-medium underline">
            Upgrade plan
          </a>
        </>
      ) : null}
    </p>
  );
}
