"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Check } from "lucide-react";

import { AuthShell } from "@/components/AuthShell";
import { Captcha, isCaptchaError } from "@/components/Captcha";
import { GoogleButton } from "@/components/GoogleButton";
import { ApiError, api, type InstanceLimits } from "@/lib/api";
import { careersSlugPreview } from "@/lib/careers";

/** Signup / first-run setup, handoff screen 13b. Company name gets a live
 * slug preview underneath. With ?google=pending (arriving from the Google
 * callback, which parked the signed account token in an httponly cookie)
 * this becomes the name-your-company onboarding step: Google already
 * vouched for the email, so no password is collected. */

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

/** "Up to 50 open jobs, 100 applications an hour and 500 candidate emails a
 * day" from the instance limits; guards that are off (0) drop out. */
function limitsSentence(limits: InstanceLimits): string {
  const parts = [
    limits.active_jobs > 0 ? `${limits.active_jobs} open jobs` : null,
    limits.applications_per_hour > 0 ? `${limits.applications_per_hour} applications an hour` : null,
    limits.emails_per_day > 0 ? `${limits.emails_per_day} candidate emails a day` : null,
  ].filter((part): part is string => part !== null);
  if (parts.length === 0) return "No usage limits on this instance";
  const last = parts.pop();
  return `Up to ${parts.length > 0 ? `${parts.join(", ")} and ${last}` : last}`;
}

/** Multi-mode only: what a stranger is signing up for (card B3). Single
 * mode is the operator's own instance; they set these limits themselves. */
function WhatYouGet({ limits }: { limits: InstanceLimits }) {
  const items = [
    "A branded careers page and apply flow, server-rendered for search engines",
    "Skill quizzes from the curated question bank, timed and scored on the server",
    limitsSentence(limits),
    "No candidate accounts and no trackers on candidate pages",
  ];
  return (
    <section
      aria-labelledby="what-you-get"
      className="rounded-md border border-edge bg-muted-fill/40 px-3.5 py-3"
    >
      <h2
        id="what-you-get"
        className="font-mono text-[10.5px] font-medium tracking-wide text-g500 uppercase"
      >
        What you get
      </h2>
      <ul className="mt-2 space-y-1.5">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-[12.5px] leading-[18px] text-g600">
            <Check
              aria-hidden
              className="mt-[3px] h-3 w-3 shrink-0 text-emerald-600 dark:text-emerald-400"
            />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SlugPreview({ slug }: { slug: string }) {
  if (slug === "") {
    return (
      <p className="mt-0.5 font-mono text-[11.5px] text-g400">
        your careers page URL will show here
      </p>
    );
  }
  return (
    <p className="mt-0.5 flex items-center gap-1.5 font-mono text-[11.5px] text-g600">
      <Check aria-hidden className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
      <span>{careersSlugPreview(slug)} - your careers page</span>
    </p>
  );
}

function SetupForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [altcha, setAltcha] = useState<string | null>(null);
  const [captchaError, setCaptchaError] = useState<ReturnType<typeof isCaptchaError>>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingEmail, setPendingEmail] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [google, setGoogle] = useState(false);
  const [googleEmail, setGoogleEmail] = useState<string | null>(null);
  const [limits, setLimits] = useState<InstanceLimits | null>(null);

  const googlePending = searchParams.get("google") === "pending";
  const slug = toSlug(companyName);

  useEffect(() => {
    let cancelled = false;
    api
      .providers()
      .then((p) => {
        if (cancelled) return;
        setGoogle(p.google);
        // the panel is for strangers on a multi-company instance only
        if (p.mode === "multi" && p.limits) setLimits(p.limits);
      })
      .catch(() => {
        /* flag stays false and the panel stays hidden; password signup is unaffected */
      });
    if (googlePending) {
      // the account token sits in an httponly cookie; the server tells us
      // which email it vouched for (or 410 when the session expired)
      api
        .googleSignupPending()
        .then((p) => {
          if (!cancelled) setGoogleEmail(p.email);
        })
        .catch((err: unknown) => {
          if (!cancelled && err instanceof ApiError && err.status === 410) setExpired(true);
          /* other failures: the banner falls back to "your Google account" */
        });
    }
    return () => {
      cancelled = true;
    };
  }, [googlePending]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    const data = new FormData(event.currentTarget);
    const company_name = String(data.get("company_name") ?? "").trim();
    try {
      if (googlePending) {
        await api.googleSignup({ company_name });
      } else {
        const email = String(data.get("email") ?? "").trim();
        const created = await api.register({
          company_name,
          email,
          password: String(data.get("password") ?? ""),
          altcha,
        });
        if (created.pending_verification) {
          // multi-mode instances verify the inbox before the workspace goes live
          setPendingEmail(email);
          return;
        }
      }
      router.push("/admin");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Signup failed";
      const captcha = isCaptchaError(message);
      setCaptchaError(captcha);
      if (captcha) {
        // the widget shows the hint; nothing else went wrong
      } else if (googlePending && /expired/i.test(message)) {
        setExpired(true);
      } else {
        setError(message);
      }
      setBusy(false);
    }
  }

  if (pendingEmail) {
    return (
      <AuthShell
        title="Check your inbox"
        subtitle={`We sent a verification link to ${pendingEmail}. Your workspace activates when you click it.`}
        footer={
          <Link href="/login" className="font-medium text-accent hover:underline">
            ← Back to log in
          </Link>
        }
      >
        <p className="text-[13px] leading-[20px] text-g600">
          Unverified signups are removed after a week. Nothing arriving? Check spam, or
          resend the link.
        </p>
        <button
          type="button"
          disabled={resent}
          onClick={() => {
            setResent(true);
            void api.resendVerification({ email: pendingEmail }).catch(() => {
              /* quiet by design - reveals nothing about which signups exist */
            });
          }}
          className="inline-flex h-9 items-center justify-center rounded-md border-[1.5px] border-edge px-4 text-[13.5px] font-semibold hover:border-accent hover:text-accent disabled:opacity-50"
        >
          {resent ? "Link resent" : "Resend the link"}
        </button>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Create your workspace"
      subtitle={
        limits ? "Name your company and we email you a link to activate it." : undefined
      }
      footer={
        <>
          Already have one?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Log in
          </Link>
        </>
      }
    >
      {googlePending && !expired ? (
        <p className="rounded-md border border-edge bg-muted-fill/40 px-3 py-2 text-[12.5px] text-g500">
          Signing up with Google as{" "}
          <span className="font-medium text-g600">{googleEmail ?? "your Google account"}</span>.
          Just name your company to finish.
        </p>
      ) : null}

      {expired ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          This Google signup session expired.{" "}
          <Link href="/login" className="font-medium underline">
            Sign in with Google again
          </Link>{" "}
          to restart.
        </p>
      ) : null}

      {!googlePending && google ? (
        <>
          <GoogleButton label="Sign up with Google" />
          <div className="flex items-center gap-3 pt-2">
            <span aria-hidden className="h-px flex-1 bg-edge" />
            <span className="font-mono text-[10.5px] tracking-wide text-g400 uppercase">
              or with email
            </span>
            <span aria-hidden className="h-px flex-1 bg-edge" />
          </div>
        </>
      ) : null}

      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        {googlePending ? null : (
          <>
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
          </>
        )}
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
          <SlugPreview slug={slug} />
        </div>
        {googlePending ? null : <Captcha onChange={setAltcha} error={captchaError} />}
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy || expired}
          className="mt-1 inline-flex h-[42px] w-full items-center justify-center rounded-md bg-inverse text-[14.5px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : "Create workspace"}
        </button>
      </form>
      {limits ? <WhatYouGet limits={limits} /> : null}
      <p className="text-center font-mono text-[10.5px] leading-4 text-g400">
        Open source · self-hostable · no candidate accounts, ever
      </p>
    </AuthShell>
  );
}

export default function SetupPage() {
  return (
    <Suspense>
      <SetupForm />
    </Suspense>
  );
}
