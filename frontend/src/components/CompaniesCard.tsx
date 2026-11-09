"use client";

import { useEffect, useState } from "react";

import { homeFor } from "@/components/CompanySwitcher";
import { api, ApiError, type CompanySeat } from "@/lib/api";

const ROLE_LABEL: Record<CompanySeat["role"], string> = {
  admin: "Admin",
  member: "Member",
  reviewer: "Reviewer",
};

/** "Your companies" on the Account page (SSO + multi-company card, slice 8):
 * every company the signed-in person holds a seat in, each with a Leave
 * action behind an inline confirm. Renders only with two or more seats (a
 * person's only company is closed by deactivation, not by leaving) and not
 * while the operator impersonates (the DELETE is refused there). Leaving
 * the active company is a full page load to the next seat's home, so no
 * screen keeps the left company's data on screen. */
export function CompaniesCard({
  impersonating = false,
  navigate = (path: string) => window.location.assign(path),
}: {
  impersonating?: boolean;
  /** test seam; leaving the active company is a hard navigation */
  navigate?: (path: string) => void;
}) {
  const [seats, setSeats] = useState<CompanySeat[] | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
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
        if (live) setSeats(null); // optional card; never block the page
      });
    return () => {
      live = false;
    };
  }, [impersonating]);

  if (impersonating || !seats || seats.length < 2) return null;

  async function leave(seat: CompanySeat) {
    setBusy(true);
    setError(null);
    try {
      const user = await api.leaveCompany(seat.company_id);
      if (seat.active) {
        navigate(homeFor(user.role));
        return;
      }
      setSeats((list) => (list ?? []).filter((s) => s.company_id !== seat.company_id));
      setConfirming(null);
      setBusy(false);
    } catch (err) {
      setBusy(false);
      setError(
        err instanceof ApiError && err.status !== 500
          ? err.detail
          : "Could not leave the company. Try again.",
      );
    }
  }

  return (
    <div className="card p-5">
      <p className="text-sm font-semibold">Your companies</p>
      <p className="mt-0.5 text-[12.5px] text-g500">
        One account, a seat in each company. Leaving a company keeps your account and your
        other companies.
      </p>
      <ul className="mt-4 divide-y divide-edge rounded-md border border-edge">
        {seats.map((seat) => (
          <li key={seat.company_id} className="px-3 py-2.5">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-medium">{seat.name}</p>
                <p className="text-[12px] text-g500">
                  {ROLE_LABEL[seat.role]}
                  {seat.active ? " · active now" : ""}
                </p>
              </div>
              {confirming === seat.company_id ? null : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setError(null);
                    setConfirming(seat.company_id);
                  }}
                  aria-label={`Leave ${seat.name}`}
                  className="inline-flex h-8 items-center rounded-md border border-edge px-3 text-[13px] font-medium hover:bg-muted-fill/50 disabled:opacity-50"
                >
                  Leave
                </button>
              )}
            </div>
            {confirming === seat.company_id ? (
              <div className="mt-2.5 rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5">
                <p className="text-[12.5px]">
                  Leave {seat.name}? You lose access to its jobs and candidates. An admin there
                  can invite you back.
                </p>
                {error ? (
                  <p role="alert" className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">
                    {error}
                  </p>
                ) : null}
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void leave(seat)}
                    className="inline-flex h-8 items-center rounded-md bg-red-600 px-3 text-[13px] font-medium text-white hover:brightness-[0.94] disabled:opacity-50"
                  >
                    {busy ? "…" : `Leave ${seat.name}`}
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
        ))}
      </ul>
    </div>
  );
}
