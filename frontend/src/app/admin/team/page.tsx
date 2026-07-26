"use client";

import { useCallback, useEffect, useState } from "react";

import { ChevronDown, MoreHorizontal, Plus } from "lucide-react";

import { team, type TeamUser, type UserRole } from "@/lib/api";

/** Team page, handoff screen 12: add-member card (email + password + role),
 * member rows (avatar with initials, role select chip, active-X-ago, ⋯
 * menu), role legend footer. Email-based invites and an Owner role are
 * D6 work — this ships the visual against the current admin/member data. */

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm outline-none focus:border-g400";
const labelCls = "text-[13.5px] font-medium";

const AVATAR_PALETTE = [
  { bg: "bg-emerald-100 dark:bg-emerald-950", text: "text-emerald-700 dark:text-emerald-300" },
  { bg: "bg-sky-100 dark:bg-sky-950", text: "text-sky-700 dark:text-sky-300" },
  { bg: "bg-amber-100 dark:bg-amber-950", text: "text-amber-700 dark:text-amber-300" },
  { bg: "bg-rose-100 dark:bg-rose-950", text: "text-rose-700 dark:text-rose-300" },
  { bg: "bg-violet-100 dark:bg-violet-950", text: "text-violet-700 dark:text-violet-300" },
];

function displayName(email: string): string {
  const local = email.split("@")[0];
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || email;
}

function initials(email: string): string {
  const name = displayName(email);
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function avatarTone(email: string): (typeof AVATAR_PALETTE)[number] {
  let hash = 0;
  for (const ch of email) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

function relativeActivity(iso: string | null, now: Date = new Date()): string {
  if (iso === null) return "never logged in";
  const diff = now.getTime() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 2) return "active now";
  if (minutes < 60) return `active ${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `active ${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `active ${days}d ago`;
  const months = Math.round(days / 30);
  return `active ${months}mo ago`;
}

export default function TeamPage() {
  const [users, setUsers] = useState<TeamUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const reload = useCallback(() => {
    team
      .list()
      .then(setUsers)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load team"),
      );
  }, []);
  useEffect(reload, [reload]);

  useEffect(() => {
    if (openMenuId === null) return;
    const close = () => setOpenMenuId(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenuId]);

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
    setOpenMenuId(null);
    try {
      await team.update(id, patch);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  const memberCount = users?.length ?? 0;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Team</h1>
          <p className="mt-1 text-[13px] text-g500">
            {users === null ? "loading…" : `${memberCount} member${memberCount === 1 ? "" : "s"}`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-inverse pr-3 pl-2 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94]"
        >
          <Plus aria-hidden className="h-[15px] w-[15px]" />
          {showForm ? "Cancel" : "Add member"}
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {showForm ? (
        <form onSubmit={create} className="card grid grid-cols-1 gap-3 p-4 sm:grid-cols-4">
          <label className="flex flex-col gap-2 sm:col-span-2">
            <span className={labelCls}>Email</span>
            <input name="email" type="email" required className={inputCls} />
          </label>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Password (min 10)</span>
            <input
              name="password"
              type="password"
              minLength={10}
              required
              className={inputCls}
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className={labelCls}>Role</span>
            <div className="relative">
              <select
                name="role"
                defaultValue="member"
                className={`${inputCls} appearance-none pr-8`}
              >
                <option value="member">member</option>
                <option value="admin">admin</option>
              </select>
              <ChevronDown
                aria-hidden
                className="pointer-events-none absolute top-1/2 right-2.5 h-3.5 w-3.5 -translate-y-1/2 text-g500"
              />
            </div>
          </label>
          <div className="sm:col-span-4">
            <button
              type="submit"
              disabled={busy}
              className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13.5px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
            >
              {busy ? "…" : "Create user"}
            </button>
          </div>
        </form>
      ) : null}

      {users === null ? (
        <div aria-busy="true" className="space-y-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-muted-fill" />
          ))}
        </div>
      ) : (
        <div className="card overflow-visible">
          <ul>
            {users.map((user) => {
              const tone = avatarTone(user.email);
              const menuOpen = openMenuId === user.id;
              return (
                <li
                  key={user.id}
                  className="flex items-center gap-3.5 border-t border-divider px-[18px] py-[14px] first:border-t-0"
                >
                  <div
                    aria-hidden
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${tone.bg} ${tone.text}`}
                  >
                    {initials(user.email)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold">
                        {displayName(user.email)}
                      </span>
                      {!user.is_active ? (
                        <span className="inline-flex h-5 items-center rounded-full border border-edge bg-muted-fill px-2 text-[11px] font-medium text-g500">
                          deactivated
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-0.5 font-mono text-[11.5px] text-g500">{user.email}</p>
                  </div>
                  <div className="relative">
                    <select
                      aria-label={`Role for ${user.email}`}
                      value={user.role}
                      onChange={(event) =>
                        patch(user.id, { role: event.target.value as UserRole })
                      }
                      className="inline-flex h-[30px] appearance-none items-center rounded-sm border border-edge bg-surface pr-7 pl-3 text-[12.5px] font-medium text-g700 outline-none focus:border-g400"
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                    <ChevronDown
                      aria-hidden
                      className="pointer-events-none absolute top-1/2 right-2 h-3 w-3 -translate-y-1/2 text-g500"
                    />
                  </div>
                  <span className="w-[110px] text-right font-mono text-[11px] text-g400">
                    {relativeActivity(user.last_login_at, now)}
                  </span>
                  <div className="relative">
                    <button
                      type="button"
                      aria-label={`Actions for ${user.email}`}
                      aria-haspopup="menu"
                      aria-expanded={menuOpen}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenMenuId((current) => (current === user.id ? null : user.id));
                      }}
                      className="inline-flex h-[30px] w-[30px] items-center justify-center rounded-sm text-g500 hover:bg-muted-fill"
                    >
                      <MoreHorizontal aria-hidden className="h-4 w-4" />
                    </button>
                    {menuOpen ? (
                      <div
                        role="menu"
                        className="absolute top-full right-0 z-10 mt-1 w-40 rounded-md border border-edge bg-surface py-1 text-left shadow-lg"
                      >
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => patch(user.id, { is_active: !user.is_active })}
                          className="block w-full px-3 py-1.5 text-left text-[13px] hover:bg-muted-fill"
                        >
                          {user.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                      </div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-5 text-[12.5px] leading-[19px] text-g500">
        <span>
          <b className="font-semibold text-g700">Admin</b> — jobs, questions, team, branding
        </span>
        <span>
          <b className="font-semibold text-g700">Member</b> — day-to-day recruiting, applicant
          review
        </span>
      </div>
    </section>
  );
}
