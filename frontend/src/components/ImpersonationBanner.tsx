"use client";

import { Eye } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { shortTime } from "@/lib/time";

/** Operator plane: shown on every admin page while the instance operator is
 * viewing a tenant account through an impersonation (GET /auth/me carries
 * `impersonation_expires_at`). The session is read-only and ends on its own
 * after an hour; the page reloads then, so the operator is never left
 * looking at a shell that no longer answers as the tenant. */
export function ImpersonationBanner({ email, expiresAt }: { email: string; expiresAt: string }) {
  const [ending, setEnding] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ms = new Date(expiresAt).getTime() - Date.now();
    if (Number.isNaN(ms)) return;
    const timer = window.setTimeout(() => window.location.reload(), Math.max(0, ms) + 1000);
    return () => window.clearTimeout(timer);
  }, [expiresAt]);

  return (
    <div
      role="status"
      data-testid="impersonation-banner"
      className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-accent bg-accent/10 px-4 py-2.5 text-[13px] text-g700"
    >
      <Eye aria-hidden className="h-[15px] w-[15px] shrink-0 text-accent" />
      <span className="min-w-0 flex-1">
        <b className="font-semibold">Viewing as {email}.</b> Instance operator access,
        read-only, ends at {shortTime(expiresAt)}. The workspace&apos;s activity feed shows
        this session.
        {failed ? " Couldn't end it, try again." : null}
      </span>
      <button
        type="button"
        disabled={ending}
        onClick={() => {
          setEnding(true);
          setFailed(false);
          api
            .endImpersonation()
            .then(() => window.location.reload())
            .catch(() => {
              setEnding(false);
              setFailed(true);
            });
        }}
        className="inline-flex h-8 items-center rounded-md border-[1.5px] border-edge px-3 text-[12.5px] font-semibold hover:border-accent hover:text-accent disabled:opacity-60"
      >
        {ending ? "Ending..." : "End impersonation"}
      </button>
    </div>
  );
}
