"use client";

import { useState } from "react";

import { api, type UserOut } from "@/lib/api";
import { useLocale } from "@/lib/i18n/locale";

/** Account page card for the second factor and "sign out everywhere"
 * (board card A6). Enrolment is two steps: the backend hands out a secret,
 * the authenticator app proves it has it with one code, and the recovery
 * codes are shown exactly once. */

const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-sm outline-none focus:border-g400";
const primaryBtn =
  "inline-flex h-8 items-center rounded-md bg-inverse px-3.5 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50";
const secondaryBtn =
  "inline-flex h-8 items-center rounded-md border border-edge px-3.5 text-[13px] font-medium hover:bg-muted-fill/50 disabled:opacity-50";

type Props = {
  user: UserOut;
  onUserChange: (user: UserOut) => void;
  /** demo instance: the shared login must keep working for the next visitor */
  locked?: boolean;
};

type Phase =
  | { kind: "idle" }
  | { kind: "enrolling"; secret: string; uri: string }
  | { kind: "codes"; codes: string[] }
  | { kind: "disabling" };

export function TwoFactorCard({ user, onUserChange, locked = false }: Props) {
  const { t } = useLocale();
  const lockedTitle = locked ? t("mfa.lockedTitle") : undefined;
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [signedOut, setSignedOut] = useState(false);

  async function run(action: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.failed"));
    } finally {
      setBusy(false);
    }
  }

  const start = () =>
    run(async () => {
      const enrol = await api.mfa.enrol();
      setPhase({ kind: "enrolling", secret: enrol.secret, uri: enrol.otpauth_uri });
    });

  async function confirm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code") ?? "");
    await run(async () => {
      const out = await api.mfa.confirm(code);
      setPhase({ kind: "codes", codes: out.recovery_codes });
      onUserChange({ ...user, mfa_enabled: true, recovery_codes_left: out.recovery_codes.length });
    });
  }

  async function disable(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("reauth") ?? "");
    await run(async () => {
      await api.mfa.disable(user.has_password ? { password: value } : { code: value });
      setPhase({ kind: "idle" });
      onUserChange({ ...user, mfa_enabled: false, recovery_codes_left: 0 });
    });
  }

  const signOutEverywhere = () =>
    run(async () => {
      await api.signOutEverywhere();
      setSignedOut(true);
    });

  const enabled = user.mfa_enabled === true;

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{t("mfa.title")}</p>
          <p className="mt-0.5 text-[12.5px] text-g500">
            {enabled ? t("mfa.on", { count: user.recovery_codes_left ?? 0 }) : t("mfa.off")}
          </p>
        </div>
        {phase.kind === "idle" ? (
          enabled ? (
            <button
              type="button"
              onClick={() => setPhase({ kind: "disabling" })}
              disabled={locked}
              title={lockedTitle}
              className={secondaryBtn}
            >
              {t("mfa.turnOff")}
            </button>
          ) : (
            <button
              type="button"
              onClick={start}
              disabled={busy || locked}
              title={lockedTitle}
              className={primaryBtn}
            >
              {busy ? "…" : t("mfa.setUp")}
            </button>
          )
        ) : null}
      </div>
      {locked ? (
        <p role="note" className="mt-3 text-[12.5px] text-g500">
          {t("mfa.locked")}
        </p>
      ) : null}

      {enabled && (user.recovery_codes_left ?? 0) < 3 && phase.kind === "idle" ? (
        <p className="mt-3 rounded-md border border-amber-300/50 bg-amber-500/10 px-3 py-2 text-[12.5px] text-amber-700 dark:text-amber-400">
          {t("mfa.fewCodes")}
        </p>
      ) : null}

      {phase.kind === "enrolling" ? (
        <form onSubmit={confirm} className="mt-4 space-y-3">
          <p className="text-[13px]">{t("mfa.addKey")}</p>
          <p className="rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5 font-mono text-[12.5px] break-all select-all">
            {phase.secret}
          </p>
          <a href={phase.uri} className="text-[12.5px] text-accent hover:underline">
            {t("mfa.openApp")}
          </a>
          <label className="flex max-w-[240px] flex-col gap-1.5">
            <span className="text-[13px] font-medium">{t("mfa.code")}</span>
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9 ]{6,7}"
              required
              className={inputCls}
            />
          </label>
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className={primaryBtn}>
              {busy ? "…" : t("mfa.turnOn")}
            </button>
            <button
              type="button"
              onClick={() => setPhase({ kind: "idle" })}
              className={secondaryBtn}
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      ) : null}

      {phase.kind === "codes" ? (
        <div className="mt-4 space-y-3">
          <p className="text-[13px] font-medium">{t("mfa.enabled")}</p>
          <p className="text-[12.5px] text-g500">{t("mfa.saveCodes")}</p>
          <ul className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-md border border-edge bg-muted-fill/40 px-3 py-2.5 font-mono text-[12.5px] select-all sm:grid-cols-5">
            {phase.codes.map((code) => (
              <li key={code}>{code}</li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => setPhase({ kind: "idle" })}
            className={secondaryBtn}
          >
            {t("mfa.savedCodes")}
          </button>
        </div>
      ) : null}

      {phase.kind === "disabling" ? (
        <form onSubmit={disable} className="mt-4 space-y-3">
          <label className="flex max-w-[280px] flex-col gap-1.5">
            <span className="text-[13px] font-medium">
              {user.has_password ? t("mfa.confirmPassword") : t("mfa.confirmCode")}
            </span>
            <input
              name="reauth"
              type={user.has_password ? "password" : "text"}
              autoComplete={user.has_password ? "current-password" : "one-time-code"}
              required
              className={inputCls}
            />
          </label>
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className={primaryBtn}>
              {busy ? "…" : t("mfa.turnOffSubmit")}
            </button>
            <button
              type="button"
              onClick={() => setPhase({ kind: "idle" })}
              className={secondaryBtn}
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      ) : null}

      {error ? (
        <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <div className="mt-5 flex items-center justify-between gap-4 border-t border-divider pt-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{t("sessions.title")}</p>
          <p className="mt-0.5 text-[12.5px] text-g500">
            {signedOut ? t("sessions.done") : t("sessions.hint")}
          </p>
        </div>
        <button
          type="button"
          onClick={signOutEverywhere}
          disabled={busy || signedOut || locked}
          title={lockedTitle}
          className={secondaryBtn}
        >
          {t("sessions.signOutEverywhere")}
        </button>
      </div>
    </div>
  );
}
