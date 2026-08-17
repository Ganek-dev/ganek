"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";

/** Reset password, handoff screen 13c (M5.7 H4 — the real flow at last).
 * Without ?token= this asks for an email and always claims success (the
 * backend never reveals whether an account exists); with ?token= it sets
 * the new password and the backend logs the user straight in. */

const inputCls =
  "h-10 w-full rounded-md border-[1.5px] border-edge bg-surface px-3.5 text-sm outline-none focus:border-accent";
const buttonCls =
  "mt-1 inline-flex h-[42px] w-full items-center justify-center rounded-md bg-inverse text-[14.5px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50";

const backToLogin = (
  <Link href="/login" className="font-medium text-accent hover:underline">
    ← Back to log in
  </Link>
);

function RequestForm() {
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await api.forgotPassword({ email: String(data.get("email") ?? "").trim() });
    } catch {
      // deliberate: even a failed request must not hint at account existence
    }
    setSent(true);
  }

  if (sent) {
    return (
      <AuthShell
        title="Check your inbox"
        subtitle="If that address has a workspace account, a reset link is on its way. It works for 45 minutes."
        footer={backToLogin}
      >
        <p className="text-[13px] leading-[20px] text-g600">
          Nothing arriving? Check spam, or ask your workspace admin to set a new password
          from the Team page.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="Enter your account email and we'll send a reset link."
      footer={backToLogin}
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        <label className="flex flex-col gap-2">
          <span className="text-[13.5px] font-medium">Email</span>
          <input
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@company.com"
            className={inputCls}
          />
        </label>
        <button type="submit" disabled={busy} className={buttonCls}>
          {busy ? "…" : "Send reset link"}
        </button>
      </form>
    </AuthShell>
  );
}

function NewPasswordForm({ token }: { token: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") ?? "");
    if (password !== String(data.get("confirm") ?? "")) {
      setError("Passwords don't match");
      return;
    }
    setBusy(true);
    try {
      await api.resetPassword({ token, new_password: password });
      router.push("/admin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Choose a new password"
      subtitle="You'll be signed in right after."
      footer={backToLogin}
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-2">
            <span className="text-[13.5px] font-medium">New password</span>
            <input
              name="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              className={inputCls}
            />
          </label>
          <span className="font-mono text-[10.5px] text-g400">at least 10 characters</span>
        </div>
        <label className="flex flex-col gap-2">
          <span className="text-[13.5px] font-medium">Repeat password</span>
          <input
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            className={inputCls}
          />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}{" "}
            <Link href="/reset" className="font-medium underline">
              Request a new link
            </Link>
          </p>
        ) : null}
        <button type="submit" disabled={busy} className={buttonCls}>
          {busy ? "…" : "Set password"}
        </button>
      </form>
    </AuthShell>
  );
}

function ResetPage() {
  const token = useSearchParams().get("token");
  return token ? <NewPasswordForm token={token} /> : <RequestForm />;
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetPage />
    </Suspense>
  );
}
