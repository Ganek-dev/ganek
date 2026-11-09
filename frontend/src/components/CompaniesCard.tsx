"use client";

import { useEffect, useState } from "react";

import { homeFor } from "@/components/CompanySwitcher";
import { api, ApiError, type CompanySeat } from "@/lib/api";
import { useLocale } from "@/lib/i18n/locale";
import type { MessageKey } from "@/lib/i18n/messages";

const ROLE_LABEL: Record<CompanySeat["role"], MessageKey> = {
  admin: "companies.roleAdmin",
  member: "companies.roleMember",
  reviewer: "companies.roleReviewer",
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
  const { t } = useLocale();
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
          : t("companies.leaveFailed"),
      );
    }
  }

  return (
    <div className="card p-5">
      <p className="text-sm font-semibold">{t("companies.title")}</p>
      <p className="mt-0.5 text-[12.5px] text-g500">{t("companies.description")}</p>
      <ul className="mt-4 divide-y divide-edge rounded-md border border-edge">
        {seats.map((seat) => (
          <li key={seat.company_id} className="px-3 py-2.5">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-medium">{seat.name}</p>
                <p className="text-[12px] text-g500">
                  {t(ROLE_LABEL[seat.role])}
                  {seat.active ? ` · ${t("companies.activeNow")}` : ""}
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
                  aria-label={t("companies.leaveCompany", { name: seat.name })}
                  className="inline-flex h-8 items-center rounded-md border border-edge px-3 text-[13px] font-medium hover:bg-muted-fill/50 disabled:opacity-50"
                >
                  {t("companies.leave")}
                </button>
              )}
            </div>
            {confirming === seat.company_id ? (
              <div className="mt-2.5 rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5">
                <p className="text-[12.5px]">
                  {t("companies.confirm", { name: seat.name })}
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
                    {busy ? "…" : t("companies.leaveCompany", { name: seat.name })}
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
                    {t("common.cancel")}
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
