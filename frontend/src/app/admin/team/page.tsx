"use client";

import { useCallback, useEffect, useState } from "react";

import { team, type TeamUser, type UserRole } from "@/lib/api";

const inputCls =
  "w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
const labelCls = "text-sm font-medium text-zinc-700 dark:text-zinc-300";
const selectCls =
  "rounded-md border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-950";

export default function TeamPage() {
  const [users, setUsers] = useState<TeamUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    team
      .list()
      .then(setUsers)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load team"),
      );
  }, []);
  useEffect(reload, [reload]);

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await team.create(
        String(data.get("email") ?? "").trim(),
        String(data.get("password") ?? ""),
        String(data.get("role") ?? "member") as UserRole,
      );
      setShowForm(false);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setBusy(false);
    }
  }

  async function patch(id: string, patch: { role?: UserRole; is_active?: boolean }) {
    setError(null);
    try {
      await team.update(id, patch);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Team</h1>
          <p className="text-sm text-zinc-500">
            Admins manage jobs, questions, users and can bulk-reject. Members do
            day-to-day recruiting.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {showForm ? "Cancel" : "Add user"}
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {showForm ? (
        <form
          onSubmit={create}
          className="grid grid-cols-1 gap-3 rounded-xl border border-zinc-200 bg-white p-4 sm:grid-cols-4 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <label className="space-y-1 sm:col-span-2">
            <span className={labelCls}>Email</span>
            <input name="email" type="email" required className={inputCls} />
          </label>
          <label className="space-y-1">
            <span className={labelCls}>Password (min 10)</span>
            <input name="password" type="password" minLength={10} required className={inputCls} />
          </label>
          <label className="space-y-1">
            <span className={labelCls}>Role</span>
            <select name="role" defaultValue="member" className={inputCls}>
              <option value="member">member</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <div className="sm:col-span-4">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
            >
              {busy ? "…" : "Create user"}
            </button>
          </div>
        </form>
      ) : null}

      {users === null ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : (
        <ul className="divide-y divide-zinc-200 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
          {users.map((user) => (
            <li key={user.id} className="flex items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <p className="truncate font-medium text-zinc-900 dark:text-zinc-50">
                  {user.email}
                  {user.is_active ? null : (
                    <span className="ml-2 rounded-full bg-zinc-200 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                      deactivated
                    </span>
                  )}
                </p>
                <p className="text-sm text-zinc-500">
                  {user.last_login_at
                    ? `last login ${new Date(user.last_login_at).toLocaleDateString("en-US")}`
                    : "never logged in"}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <select
                  aria-label={`Role for ${user.email}`}
                  value={user.role}
                  onChange={(e) => patch(user.id, { role: e.target.value as UserRole })}
                  className={selectCls}
                >
                  <option value="member">member</option>
                  <option value="admin">admin</option>
                </select>
                <button
                  type="button"
                  onClick={() => patch(user.id, { is_active: !user.is_active })}
                  className="rounded-md border border-zinc-300 px-2 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                >
                  {user.is_active ? "Deactivate" : "Reactivate"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
