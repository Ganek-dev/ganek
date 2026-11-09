"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type CompanySeat } from "@/lib/api";

const ROLE_LABEL: Record<CompanySeat["role"], string> = {
  admin: "Admin",
  member: "Member",
  reviewer: "Reviewer",
};

/** Where a seat's role lands after a switch: reviewers have their own shell. */
export function homeFor(role: CompanySeat["role"]): string {
  return role === "reviewer" ? "/review" : "/admin";
}

/** Company switcher (SSO + multi-company card, slice 3). Lists the seats from
 * GET /auth/companies and renders only when the user holds two or more;
 * a single-seat user sees `fallback` (the plain company name, or nothing).
 * A switch is a full page load to the new seat's home, so no screen keeps
 * the previous company's data or memoized reads on screen. Hidden while the
 * operator impersonates (the switch POST is read-only refused there). */
export function CompanySwitcher({
  tone = "dark",
  impersonating = false,
  fallback = null,
  navigate = (path: string) => window.location.assign(path),
}: {
  /** dark = the admin sidebar, light = the reviewer header */
  tone?: "dark" | "light";
  impersonating?: boolean;
  fallback?: React.ReactNode;
  /** test seam; a real switch is a hard navigation */
  navigate?: (path: string) => void;
}) {
  const [seats, setSeats] = useState<CompanySeat[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (impersonating) return;
    let live = true;
    api
      .companies()
      .then((list) => {
        if (live) setSeats(list);
      })
      .catch(() => {
        if (live) setSeats(null); // the switcher is optional; never block the shell
      });
    return () => {
      live = false;
    };
  }, [impersonating]);

  if (impersonating || !seats || seats.length < 2) return <>{fallback}</>;

  const active = seats.find((s) => s.active) ?? seats[0];

  async function onChange(companyId: string) {
    const target = seats?.find((s) => s.company_id === companyId);
    if (!target || target.active) return;
    setBusy(true);
    setError(null);
    try {
      const user = await api.switchCompany(companyId);
      navigate(homeFor(user.role));
    } catch (err) {
      setBusy(false);
      setError(
        err instanceof ApiError && err.status !== 500
          ? err.detail
          : "Could not switch company. Try again.",
      );
    }
  }

  const dark = tone === "dark";
  return (
    <div className={dark ? "px-3 pb-3" : "min-w-0"}>
      <label
        htmlFor="company-switcher"
        className={
          dark
            ? "mb-1 block px-1 text-[11px] font-medium uppercase tracking-wide text-zinc-500"
            : "sr-only"
        }
      >
        Company
      </label>
      <select
        id="company-switcher"
        value={active.company_id}
        disabled={busy}
        onChange={(event) => void onChange(event.target.value)}
        className={
          dark
            ? "h-9 w-full truncate rounded-md border border-white/15 bg-white/5 px-2 text-[13px] text-zinc-200 hover:border-white/30 disabled:opacity-60"
            : "h-9 max-w-[220px] truncate rounded-md border border-edge bg-surface px-2 text-[13.5px] font-medium text-g700 hover:border-accent disabled:opacity-60"
        }
      >
        {seats.map((seat) => (
          <option key={seat.company_id} value={seat.company_id}>
            {seat.name} ({ROLE_LABEL[seat.role]})
          </option>
        ))}
      </select>
      {error ? (
        <p role="alert" className={`mt-1 text-[12px] ${dark ? "text-red-300" : "text-red-700"}`}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
