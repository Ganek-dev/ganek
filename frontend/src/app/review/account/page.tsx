"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AvailabilityCard } from "@/components/AvailabilityCard";
import { TwoFactorCard } from "@/components/TwoFactorCard";
import { api, type UserOut } from "@/lib/api";

/** Reviewer account (scorecards spec 5.2): display name, interview
 * location (the availability card), 2FA and sign-out-everywhere. The
 * /admin/account page cannot serve a reviewer - the admin layout sends them
 * away - so this reuses its cards without the settings tabs and the
 * password form (the reviewer reset flow covers a lost password). */

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm outline-none focus:border-g400";

export default function ReviewAccountPage() {
  const [user, setUser] = useState<UserOut | null>(null);
  const [demo, setDemo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => {
        /* the layout handles the 401 redirect */
      });
    api
      .providers()
      .then((p) => setDemo(p.demo === true))
      .catch(() => {
        /* the demo lock stays off */
      });
  }, []);

  async function saveName(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("display_name") ?? "").trim();
    setBusy(true);
    setSaved(false);
    try {
      setUser(await api.updateProfile(value || null));
      setSaved(true);
    } catch {
      /* the field keeps the typed value; a retry re-submits */
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="max-w-[680px] space-y-5">
      <Link
        href="/review"
        className="inline-flex items-center gap-1.5 text-[13px] text-g500 hover:text-g700"
      >
        <ArrowLeft size={14} aria-hidden />
        Back to candidates
      </Link>
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Account</h1>

      <div className="card flex flex-col gap-4 p-5">
        <div>
          <p className="text-sm font-semibold">Profile</p>
          <p className="mt-0.5 text-[12.5px] text-g500">Shown to teammates on scorecards.</p>
        </div>
        <form onSubmit={saveName} className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:gap-3">
          <label className="flex flex-1 flex-col gap-1.5">
            <span className="text-[13px] font-medium">Display name</span>
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
            disabled={busy || !user}
            className="inline-flex h-9 items-center rounded-md border border-edge px-3.5 text-[13px] font-medium hover:bg-muted-fill/50 disabled:opacity-50"
          >
            {busy ? "…" : saved ? "Saved" : "Save name"}
          </button>
        </form>
      </div>

      {user ? <TwoFactorCard user={user} onUserChange={setUser} locked={demo} /> : null}

      <AvailabilityCard />
    </section>
  );
}
