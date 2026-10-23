"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { CopyButton } from "@/components/CopyButton";
import { api, companyApi, type CompanyAdmin } from "@/lib/api";
import { careersDisplay, careersUrl } from "@/lib/careers";

/** Email-verification landing (M5.7 H4, polished in card B3): the link
 * from the signup email. Verifies on arrival; the backend logs the admin
 * straight in. Instead of bouncing to the dashboard, the page says the
 * workspace is live and hands over the careers URL, the one thing a new
 * admin wants to copy first. A stale/second click of an already-used link
 * lands here too, which is the friendly outcome. */

type State =
  | { kind: "verifying" }
  | { kind: "failed" }
  | { kind: "live"; email: string; company: CompanyAdmin | null };

function VerifyInner() {
  const token = useSearchParams().get("token");
  const [state, setState] = useState<State>({ kind: "verifying" });

  useEffect(() => {
    if (!token) return; // rendered as failed below, no state write needed
    let cancelled = false;
    (async () => {
      try {
        const user = await api.verifyEmail({ token });
        // the session cookie is set now; the company name and slug are
        // decoration, so a failed lookup still lands
        const company = await companyApi.get().catch(() => null);
        if (!cancelled) setState({ kind: "live", email: user.email, company });
      } catch {
        if (!cancelled) setState({ kind: "failed" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (state.kind === "failed" || !token) {
    return (
      <AuthShell
        title="This link didn't work"
        subtitle="Verification links expire after a few days, and unverified signups are removed after a week."
        footer={
          <Link href="/setup" className="font-medium text-accent hover:underline">
            Start a new signup
          </Link>
        }
      >
        <p className="text-[13px] leading-[20px] text-g600">
          If you signed up recently, log in to request a fresh link, or simply sign up again
          with the same email.
        </p>
      </AuthShell>
    );
  }

  if (state.kind === "live") {
    const { email, company } = state;
    return (
      <AuthShell
        title={company ? `${company.name} is live` : "Your workspace is live"}
        subtitle={`${email} is verified. Your careers page is ready to share.`}
      >
        {company ? (
          <div className="flex items-center gap-2 rounded-md border border-edge bg-muted-fill/40 px-3 py-2">
            <p className="min-w-0 flex-1 truncate font-mono text-[12px] text-g600">
              {careersDisplay(company.mode, company.slug)}
            </p>
            <CopyButton
              text={careersUrl(company.mode, company.slug)}
              label="Copy careers URL"
            />
          </div>
        ) : null}
        <Link
          href="/admin"
          className="mt-1 inline-flex h-[42px] w-full items-center justify-center rounded-md bg-inverse text-[14.5px] font-semibold text-inverse-foreground hover:brightness-[0.94]"
        >
          Go to your dashboard
        </Link>
        <p className="text-center text-[12.5px] leading-[18px] text-g500">
          The dashboard checklist walks you through branding, your first job and its quiz.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Verifying your email…" subtitle="One moment.">
      <div aria-busy="true" className="h-9 animate-pulse rounded-md bg-muted-fill" />
    </AuthShell>
  );
}

export default function VerifyPage() {
  return (
    <Suspense>
      <VerifyInner />
    </Suspense>
  );
}
