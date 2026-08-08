"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { GoogleButton } from "@/components/GoogleButton";
import { ApiError, api, publicInvites, type PublicInvite } from "@/lib/api";

/** Team-invite accept page (magic link from the D6 invite email): shows
 * who's invited where, takes a password, and lands the new user in /admin
 * already logged in. Invalid/revoked links 404, past-deadline links 410. */

const inputCls =
  "h-10 w-full rounded-md border-[1.5px] border-edge bg-surface px-3.5 text-sm outline-none focus:border-accent";

const ROLE_LABELS: Record<PublicInvite["role"], string> = {
  admin: "an Admin",
  member: "a Member",
};

const GOOGLE_ERRORS: Record<string, string> = {
  "google-email-mismatch":
    "That Google account doesn't match this invite. Use the Google account for the invited email, or set a password instead.",
  "email-taken": "An account with this email already exists.",
  "google-invalid": "Google sign-in didn't complete. Try again or set a password below.",
};

function InviteAcceptForm() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [invite, setInvite] = useState<PublicInvite | null>(null);
  const [dead, setDead] = useState<"invalid" | "expired" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [google, setGoogle] = useState(false);

  const googleError = GOOGLE_ERRORS[searchParams.get("error") ?? ""] ?? null;

  useEffect(() => {
    let cancelled = false;
    api
      .providers()
      .then((p) => {
        if (!cancelled) setGoogle(p.google);
      })
      .catch(() => {
        /* flag stays false — password accept is unaffected */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    publicInvites
      .get(token)
      .then(setInvite)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 410) setDead("expired");
        else if (err instanceof ApiError && err.status === 404) setDead("invalid");
        else setError(err instanceof Error ? err.message : "Failed to load invite");
      });
  }, [token]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await publicInvites.accept(token, String(data.get("password") ?? ""));
      router.push("/admin");
    } catch (err) {
      if (err instanceof ApiError && err.status === 410) {
        setDead("expired");
      } else if (err instanceof ApiError && err.status === 404) {
        setDead("invalid");
      } else {
        setError(err instanceof Error ? err.message : "Failed to accept invite");
        setBusy(false);
      }
    }
  }

  if (dead !== null) {
    return (
      <AuthShell
        title={dead === "expired" ? "This invite has expired" : "Invite not found"}
        subtitle={
          dead === "expired"
            ? "Ask the person who invited you to resend it — invites stop working after 7 days."
            : "This invite link is not valid anymore. It may have been revoked or already used."
        }
      >
        {null}
      </AuthShell>
    );
  }

  if (invite === null) {
    return (
      <AuthShell title="Checking your invite…">
        {error ? (
          <p role="alert" className="text-center text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : (
          <div aria-busy="true" className="space-y-3">
            <div className="h-10 animate-pulse rounded-md bg-muted-fill" />
            <div className="h-10 animate-pulse rounded-md bg-muted-fill" />
          </div>
        )}
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={`Join ${invite.company_name}`}
      subtitle={
        <>
          You&apos;ve been invited as {ROLE_LABELS[invite.role]}. Continue as{" "}
          <span className="font-mono text-[12.5px] text-g600">{invite.email}</span> to get
          started.
        </>
      }
    >
      {googleError ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {googleError}
        </p>
      ) : null}

      {google ? (
        <>
          <GoogleButton href={`/api/v1/auth/google/start?invite=${encodeURIComponent(token)}`} />
          <div className="flex items-center gap-3 pt-2">
            <span aria-hidden className="h-px flex-1 bg-edge" />
            <span className="font-mono text-[10.5px] tracking-wide text-g400 uppercase">
              or set a password
            </span>
            <span aria-hidden className="h-px flex-1 bg-edge" />
          </div>
        </>
      ) : null}

      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        <label className="flex flex-col gap-2">
          <span className="text-[13.5px] font-medium">Password</span>
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={10}
            required
            placeholder="10+ characters"
            className={inputCls}
          />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy}
          className="mt-1 inline-flex h-[42px] w-full items-center justify-center rounded-md bg-inverse text-[14.5px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : "Accept invite"}
        </button>
      </form>
      <p className="text-center font-mono text-[10.5px] leading-4 text-g400">
        Joining {invite.company_name}&apos;s hiring workspace on vetd
      </p>
    </AuthShell>
  );
}

export default function InviteAcceptPage() {
  return (
    <Suspense>
      <InviteAcceptForm />
    </Suspense>
  );
}
