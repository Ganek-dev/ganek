"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { GoogleButton } from "@/components/GoogleButton";
import { SsoButton } from "@/components/SsoButton";
import Link from "next/link";

import {
  ApiError,
  api,
  clearSharedGets,
  publicInvites,
  type PublicInvite,
  type UserOut,
} from "@/lib/api";
import { homePath } from "@/lib/home";

/** Team-invite accept page (magic link from the D6 invite email): shows
 * who's invited where, takes a password, and lands the new user in /admin
 * already logged in. Invalid/revoked links 404, past-deadline links 410.
 * An email that already has an account (in another company) signs in and
 * joins instead (card "SSO + multi-company user membership", slice 7). A new
 * account can also be created through Google or the instance's OpenID
 * Connect provider (slice 11), which must vouch for the invited email. */

const inputCls =
  "h-10 w-full rounded-md border-[1.5px] border-edge bg-surface px-3.5 text-sm outline-none focus:border-accent";

const ROLE_LABELS: Record<PublicInvite["role"], string> = {
  admin: "an Admin",
  member: "a Member",
  reviewer: "a Reviewer",
};

const SIGN_IN_ERRORS: Record<string, string> = {
  "google-email-mismatch":
    "That Google account doesn't match this invite. Use the Google account for the invited email, or set a password instead.",
  "email-taken": "An account with this email already exists.",
  "google-invalid": "Google sign-in didn't complete. Try again or set a password below.",
  "oidc-email-mismatch":
    "Your single sign-on account didn't confirm the invited email. Sign in there as the invited address, or set a password instead.",
  "oidc-invalid": "Single sign-on didn't complete. Try again or set a password below.",
  "oidc-linked":
    "That single sign-on account already belongs to another Ganek account. Sign in with it instead, or set a password below.",
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
  // the OpenID Connect button label, or null when the instance has none
  const [sso, setSso] = useState<string | null>(null);
  // existing-account invites: who is signed in here (null = nobody)
  const [me, setMe] = useState<UserOut | null | undefined>(undefined);

  const signInError = SIGN_IN_ERRORS[searchParams.get("error") ?? ""] ?? null;

  useEffect(() => {
    let cancelled = false;
    api
      .providers()
      .then((p) => {
        if (cancelled) return;
        setGoogle(p.google);
        setSso(p.oidc ? (p.oidc_name ?? "SSO") : null);
      })
      .catch(() => {
        /* flags stay off - password accept is unaffected */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!invite?.existing_account) return;
    let cancelled = false;
    api
      .me()
      .then((user) => {
        if (!cancelled) setMe(user);
      })
      .catch(() => {
        if (!cancelled) setMe(null);
      });
    return () => {
      cancelled = true;
    };
  }, [invite]);

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
      const user = await publicInvites.accept(token, String(data.get("password") ?? ""));
      router.push(homePath(user));
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

  async function handleJoin() {
    setError(null);
    setBusy(true);
    try {
      const user = await publicInvites.join(token);
      clearSharedGets(); // the cached /me still names the previous company
      router.push(homePath(user));
    } catch (err) {
      if (err instanceof ApiError && err.status === 410) {
        setDead("expired");
      } else if (err instanceof ApiError && err.status === 404) {
        setDead("invalid");
      } else {
        setError(err instanceof Error ? err.message : "Failed to join");
        setBusy(false);
      }
    }
  }

  async function handleSignOut() {
    setBusy(true);
    try {
      await api.logout();
    } catch {
      /* the session may already be gone */
    }
    clearSharedGets();
    setMe(null);
    setBusy(false);
  }

  if (dead !== null) {
    return (
      <AuthShell
        title={dead === "expired" ? "This invite has expired" : "Invite not found"}
        subtitle={
          dead === "expired"
            ? "Ask the person who invited you to resend it - invites stop working after 7 days."
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

  if (invite.existing_account) {
    const signedInAsInvitee =
      me != null && me.email.toLowerCase() === invite.email.toLowerCase();
    return (
      <AuthShell
        title={`Join ${invite.company_name}`}
        subtitle={
          <>
            You&apos;ve been invited as {ROLE_LABELS[invite.role]}.{" "}
            <span className="font-mono text-[12.5px] text-g600">{invite.email}</span> already
            has a Ganek account, so you join with it.
          </>
        }
      >
        {me === undefined ? (
          <div aria-busy="true" className="h-[42px] animate-pulse rounded-md bg-muted-fill" />
        ) : signedInAsInvitee ? (
          <>
            {error ? (
              <p role="alert" className="text-sm text-red-600 dark:text-red-400">
                {error}
              </p>
            ) : null}
            <button
              type="button"
              onClick={handleJoin}
              disabled={busy}
              className="inline-flex h-[42px] w-full items-center justify-center rounded-md bg-inverse text-[14.5px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
            >
              {busy ? "…" : `Join ${invite.company_name}`}
            </button>
            <p className="text-center text-[12.5px] text-g500">
              Your other companies stay. Switch between them from the sidebar.
            </p>
          </>
        ) : me ? (
          <>
            <p className="text-sm text-g600">
              You&apos;re signed in as{" "}
              <span className="font-mono text-[12.5px]">{me.email}</span>. Sign out and sign in
              as <span className="font-mono text-[12.5px]">{invite.email}</span> to join.
            </p>
            <button
              type="button"
              onClick={handleSignOut}
              disabled={busy}
              className="inline-flex h-[42px] w-full items-center justify-center rounded-md border-[1.5px] border-edge text-[14.5px] font-semibold hover:bg-muted-fill disabled:opacity-50"
            >
              Sign out
            </button>
          </>
        ) : (
          <Link
            href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}
            className="inline-flex h-[42px] w-full items-center justify-center rounded-md bg-inverse text-[14.5px] font-semibold text-inverse-foreground hover:brightness-[0.94]"
          >
            Sign in to join
          </Link>
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
      {signInError ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {signInError}
        </p>
      ) : null}

      {google || sso ? (
        <>
          {sso ? (
            <SsoButton
              name={sso}
              href={`/api/v1/auth/oidc/start?invite=${encodeURIComponent(token)}`}
            />
          ) : null}
          {google ? (
            <GoogleButton href={`/api/v1/auth/google/start?invite=${encodeURIComponent(token)}`} />
          ) : null}
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
        Joining {invite.company_name}&apos;s hiring workspace on Ganek
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
