"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";

/** Login, handoff screen 13a. Google button is a placeholder until D6
 * OAuth work lands; email/password sign-in is real. */

const inputCls =
  "h-10 w-full rounded-md border-[1.5px] border-edge bg-surface px-3.5 text-sm outline-none focus:border-accent";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await api.login({
        email: String(data.get("email") ?? "").trim(),
        password: String(data.get("password") ?? ""),
      });
      router.push("/admin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Log in to your workspace"
      footer={
        <>
          New to vetd?{" "}
          <Link href="/setup" className="font-medium text-accent hover:underline">
            Create a workspace
          </Link>
        </>
      }
    >
      <button
        type="button"
        disabled
        title="Google sign-in lands with D6 OAuth work"
        className="inline-flex h-10 w-full items-center justify-center gap-2.5 rounded-md border border-edge bg-surface text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
      >
        <span
          aria-hidden
          className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full border-[1.5px] border-strong font-heading text-[11px] font-bold"
        >
          G
        </span>
        Continue with Google
      </button>

      <div className="flex items-center gap-3 pt-2">
        <span aria-hidden className="h-px flex-1 bg-edge" />
        <span className="font-mono text-[10.5px] tracking-wide text-g400 uppercase">
          or with email
        </span>
        <span aria-hidden className="h-px flex-1 bg-edge" />
      </div>

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
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label htmlFor="password" className="text-[13.5px] font-medium">
              Password
            </label>
            <Link href="/reset" className="text-xs text-accent hover:underline">
              Forgot?
            </Link>
          </div>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className={inputCls}
          />
        </div>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy}
          className="mt-1 inline-flex h-[42px] w-full items-center justify-center rounded-md bg-inverse text-[14.5px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : "Log in"}
        </button>
      </form>
    </AuthShell>
  );
}
