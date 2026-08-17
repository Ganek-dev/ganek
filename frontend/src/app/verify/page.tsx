"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";

/** Email-verification landing (M5.7 H4): the link from the signup email.
 * Verifies on arrival — the backend logs the admin straight in and a
 * stale/second click of an already-used link stays friendly. */

function VerifyInner() {
  const router = useRouter();
  const token = useSearchParams().get("token");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!token) return; // rendered as failed below, no state write needed
    let cancelled = false;
    api
      .verifyEmail({ token })
      .then(() => {
        if (!cancelled) router.replace("/admin");
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [token, router]);

  if (failed || !token) {
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
          If you signed up recently, log in to request a fresh link — or simply sign up
          again with the same email.
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
