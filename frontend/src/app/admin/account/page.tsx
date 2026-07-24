"use client";

import { useState } from "react";

import { api } from "@/lib/api";

const inputCls =
  "w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
const labelCls = "text-sm font-medium text-zinc-700 dark:text-zinc-300";

export default function AccountPage() {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

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
    <section className="max-w-sm space-y-4">
      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Change password</h1>
      <p className="text-sm text-zinc-500">
        Changing your password signs out every other session.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <label className="block space-y-1">
          <span className={labelCls}>Current password</span>
          <input name="current" type="password" required className={inputCls} />
        </label>
        <label className="block space-y-1">
          <span className={labelCls}>New password (min 10)</span>
          <input name="next" type="password" minLength={10} required className={inputCls} />
        </label>
        <label className="block space-y-1">
          <span className={labelCls}>Confirm new password</span>
          <input name="confirm" type="password" minLength={10} required className={inputCls} />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
        {done ? (
          <p className="text-sm text-green-700 dark:text-green-400">Password changed.</p>
        ) : null}
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {busy ? "…" : "Update password"}
        </button>
      </form>
    </section>
  );
}
