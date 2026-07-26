"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Check } from "lucide-react";

import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";

/** Signup / first-run setup, handoff screen 13b. Company name gets a live
 * slug preview underneath. Routed at /setup since the backend register
 * endpoint is bootstrap-only; renaming to /register can happen later. */

const inputCls =
  "h-10 w-full rounded-md border-[1.5px] border-edge bg-surface px-3.5 text-sm outline-none focus:border-accent";

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

export default function SetupPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [companyName, setCompanyName] = useState("");

  const slug = toSlug(companyName);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await api.register({
        company_name: String(data.get("company_name") ?? "").trim(),
        email: String(data.get("email") ?? "").trim(),
        password: String(data.get("password") ?? ""),
      });
      router.push("/admin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Create your workspace"
      footer={
        <>
          Already have one?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        <label className="flex flex-col gap-2">
          <span className="text-[13.5px] font-medium">Work email</span>
          <input
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@company.com"
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-2">
          <span className="text-[13.5px] font-medium">Password</span>
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={10}
            required
            placeholder="10+ characters"
            className={inputCls}
          />
        </label>
        <div className="flex flex-col gap-2">
          <label htmlFor="company_name" className="text-[13.5px] font-medium">
            Company name
          </label>
          <input
            id="company_name"
            name="company_name"
            type="text"
            required
            placeholder="Acme Labs"
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            className={inputCls}
          />
          {slug === "" ? (
            <p className="mt-0.5 font-mono text-[11.5px] text-g400">
              your careers page URL will show here
            </p>
          ) : (
            <p className="mt-0.5 flex items-center gap-1.5 font-mono text-[11.5px] text-g600">
              <Check aria-hidden className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
              <span>
                {slug}
                <span className="text-g400">.vetd.dev</span> — your careers page
              </span>
            </p>
          )}
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
          {busy ? "…" : "Create workspace"}
        </button>
      </form>
      <p className="text-center font-mono text-[10.5px] leading-4 text-g400">
        Open source · self-hostable · no candidate accounts, ever
      </p>
    </AuthShell>
  );
}
