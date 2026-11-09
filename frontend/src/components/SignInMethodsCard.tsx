"use client";

import { useState } from "react";

import { api, ApiError, type SignInMethod, type UserOut } from "@/lib/api";

interface Row {
  method: SignInMethod;
  label: string;
  linked: boolean;
}

/** "Sign-in methods" on the Account page (SSO + multi-company card, slice
 * 12): whether this account's Google and SSO identities are linked, with an
 * Unlink action behind an inline confirm. A method shows when the instance
 * offers it or the account still has it linked (an operator may have turned
 * the provider off since). Unlink is disabled while it is the account's only
 * way in; the server refuses that case too. Nothing is linked from here:
 * signing in with the provider once links it, as before. */
export function SignInMethodsCard({
  user,
  google,
  oidcName,
  locked = false,
  onUserChange,
}: {
  user: UserOut;
  /** Google sign-in is configured on this instance */
  google: boolean;
  /** the SSO button label when generic OIDC is configured, else undefined */
  oidcName?: string;
  /** demo instance or operator impersonation: read-only */
  locked?: boolean;
  onUserChange: (user: UserOut) => void;
}) {
  const [confirming, setConfirming] = useState<SignInMethod | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const googleLinked = user.google_linked === true;
  const ssoLinked = user.sso_linked === true;
  const rows: Row[] = [];
  if (google || googleLinked) rows.push({ method: "google", label: "Google", linked: googleLinked });
  if (oidcName || ssoLinked) {
    rows.push({ method: "sso", label: oidcName || "Single sign-on", linked: ssoLinked });
  }
  if (rows.length === 0) return null;

  function onlyWayIn(method: SignInMethod): boolean {
    if (user.has_password) return false;
    return method === "google" ? !ssoLinked : !googleLinked;
  }

  async function unlink(row: Row) {
    setBusy(true);
    setError(null);
    try {
      onUserChange(await api.unlinkSignInMethod(row.method));
      setConfirming(null);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status !== 500
          ? err.detail
          : `Could not unlink ${row.label}. Try again.`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-5">
      <p className="text-sm font-semibold">Sign-in methods</p>
      <p className="mt-0.5 text-[12.5px] text-g500">
        Outside accounts that can sign you in. Signing in with one links it.
      </p>
      <ul className="mt-4 divide-y divide-edge rounded-md border border-edge">
        {rows.map((row) => {
          const only = row.linked && onlyWayIn(row.method);
          return (
            <li key={row.method} className="px-3 py-2.5">
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13.5px] font-medium">{row.label}</p>
                  <p className="text-[12px] text-g500">
                    {row.linked
                      ? only
                        ? "Linked · your only way to sign in"
                        : "Linked"
                      : `Not linked · sign in with ${row.label} once to link it`}
                  </p>
                </div>
                {row.linked && confirming !== row.method ? (
                  <button
                    type="button"
                    disabled={busy || locked || only}
                    title={
                      only
                        ? "Add a password first (Forgot password on the sign-in page)"
                        : undefined
                    }
                    onClick={() => {
                      setError(null);
                      setConfirming(row.method);
                    }}
                    aria-label={`Unlink ${row.label}`}
                    className="inline-flex h-8 items-center rounded-md border border-edge px-3 text-[13px] font-medium hover:bg-muted-fill/50 disabled:opacity-50"
                  >
                    Unlink
                  </button>
                ) : null}
              </div>
              {confirming === row.method ? (
                <div className="mt-2.5 rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5">
                  <p className="text-[12.5px]">
                    Unlink {row.label}? You can no longer sign in with it until you link it
                    again by signing in with it.
                  </p>
                  {error ? (
                    <p
                      role="alert"
                      className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400"
                    >
                      {error}
                    </p>
                  ) : null}
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void unlink(row)}
                      className="inline-flex h-8 items-center rounded-md bg-inverse px-3 text-[13px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
                    >
                      {busy ? "…" : `Unlink ${row.label}`}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setConfirming(null);
                        setError(null);
                      }}
                      className="inline-flex h-8 items-center rounded-md border border-edge px-3 text-[13px] font-medium hover:bg-muted-fill/50 disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
