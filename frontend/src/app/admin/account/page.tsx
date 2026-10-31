"use client";

import { Suspense, useEffect, useState } from "react";

import { AvailabilityCard } from "@/components/AvailabilityCard";
import { SettingsTabs } from "@/components/SettingsTabs";
import { TwoFactorCard } from "@/components/TwoFactorCard";
import { api, type UserOut } from "@/lib/api";

/** Account settings, handoff screen 15 - restyled Profile + Password cards
 * against the current data model. Email notifications, Google connection
 * and the danger-zone self-delete need models scheduled for D5/D6 and are
 * intentionally omitted here. */

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm outline-none focus:border-g400";
const labelCls = "text-[13px] font-medium";

function initials(email: string, displayName?: string | null): string {
  if (displayName?.trim()) {
    const parts = displayName.trim().split(/\s+/);
    return (parts.length >= 2 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase();
  }
  const local = email.split("@")[0];
  const parts = local.split(/[._-]+/).filter(Boolean);
  const source = parts.length >= 2 ? parts[0][0] + parts[1][0] : local.slice(0, 2);
  return source.toUpperCase();
}

function AccountContent() {
  const [user, setUser] = useState<UserOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [nameBusy, setNameBusy] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => {
        // layout handles the 401 redirect; leave the page in a graceful empty state
      });
    api
      .providers()
      .then((p) => {
        setDemo(p.demo === true);
      })
      .catch(() => {
        /* card stays hidden */
      });
  }, []);

  async function saveName(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("display_name") ?? "").trim();
    setNameBusy(true);
    setNameSaved(false);
    try {
      setUser(await api.updateProfile(value || null));
      setNameSaved(true);
    } catch {
      /* the field keeps the typed value; a retry re-submits */
    } finally {
      setNameBusy(false);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setDone(false);
    const form = event.currentTarget;
    const data = new FormData(form);
    const current = String(data.get("current") ?? "");
    const next = String(data.get("next") ?? "");
    const confirm = String(data.get("confirm") ?? "");
    if (next !== confirm) {
      setError("New passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      form.reset();
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="max-w-[680px] space-y-5">
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Account</h1>
      <SettingsTabs />

      <div className="card flex flex-col gap-4 p-5">
        <div className="flex items-center gap-4">
          <div
            aria-hidden
            className="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full text-lg font-bold text-accent"
            style={{ background: "color-mix(in oklab, var(--accent) 15%, var(--surface))" }}
          >
            {user ? initials(user.email, user.display_name) : "· ·"}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Profile</p>
            <p className="mt-0.5 text-[12.5px] text-g500">
              Shown to teammates on notes and activity.
            </p>
          </div>
          {user ? (
            <span className="inline-flex h-5 items-center rounded-full border border-accent/25 bg-accent/10 px-2 text-[11px] font-medium text-accent capitalize">
              {user.role}
            </span>
          ) : null}
        </div>
        <form onSubmit={saveName} className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:gap-3">
          <label className="flex flex-1 flex-col gap-1.5">
            <span className={labelCls}>Display name</span>
            <input
              key={user?.id ?? "anon"}
              name="display_name"
              type="text"
              maxLength={100}
              defaultValue={user?.display_name ?? ""}
              placeholder={user?.display_label ?? ""}
              className={inputCls}
            />
          </label>
          <button
            type="submit"
            disabled={nameBusy || !user}
            className="inline-flex h-9 items-center rounded-md border border-edge px-3.5 text-[13px] font-medium hover:bg-muted-fill/50 disabled:opacity-50"
          >
            {nameBusy ? "…" : nameSaved ? "Saved" : "Save name"}
          </button>
        </form>
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className={labelCls}>Email</span>
            <input
              aria-label="Email"
              type="email"
              value={user?.email ?? ""}
              readOnly
              className={`${inputCls} font-mono text-[12.5px] text-g600`}
            />
          </label>
          <div className="flex flex-col gap-1.5">
            <span className={labelCls}>Role</span>
            <p className="rounded-md border border-edge bg-muted-fill/40 px-3 py-2 text-[12.5px] text-g500 capitalize">
              {user?.role ?? "-"} · assigned by workspace admin
            </p>
          </div>
        </div>
      </div>

      <div className="card p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold">Password</p>
            <p className="mt-0.5 text-[12.5px] text-g500">
              {user && !user.has_password
                ? "How you access this workspace."
                : "Changing your password signs out every other session; so does the button under Sessions below."}
            </p>
          </div>
        </div>
        {user && !user.has_password ? (
          <p className="mt-4 rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5 text-[12.5px] text-g500">
            You sign in with Google - this account has no password.
          </p>
        ) : demo ? (
          <p
            role="note"
            className="mt-4 rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5 text-[12.5px] text-g500"
          >
            Password changes are off on the demo workspace: the login is shared with every
            visitor.
          </p>
        ) : (
          <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3.5 sm:grid-cols-3">
          <label className="flex flex-col gap-1.5">
            <span className={labelCls}>Current password</span>
            <input name="current" type="password" required className={inputCls} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className={labelCls}>New password (min 10)</span>
            <input name="next" type="password" minLength={10} required className={inputCls} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className={labelCls}>Confirm new password</span>
            <input name="confirm" type="password" minLength={10} required className={inputCls} />
          </label>
          <div className="sm:col-span-3">
            {error ? (
              <p role="alert" className="mb-2 text-sm text-red-600 dark:text-red-400">
                {error}
              </p>
            ) : null}
            {done ? (
              <p className="mb-2 text-sm text-emerald-700 dark:text-emerald-400">
                Password changed.
              </p>
            ) : null}
            <button
              type="submit"
              disabled={busy}
              className="inline-flex h-8 items-center rounded-md bg-inverse px-3.5 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
            >
              {busy ? "…" : "Update password"}
            </button>
          </div>
        </form>
        )}
      </div>

      {user ? <TwoFactorCard user={user} onUserChange={setUser} locked={demo} /> : null}

      <AvailabilityCard />

      <p className="text-[12.5px] text-g500">
        Email notification preferences and account deletion are planned for a later
        milestone.
      </p>
    </section>
  );
}

export default function AccountPage() {
  return (
    <Suspense>
      <AccountContent />
    </Suspense>
  );
}
