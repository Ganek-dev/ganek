"use client";

import { Suspense, useCallback, useEffect, useState } from "react";

import { useSearchParams } from "next/navigation";

import { SettingsTabs } from "@/components/SettingsTabs";
import {
  billingApi,
  clearSharedGets,
  companyApi,
  type BillingInterval,
  type BillingOut,
  type PlanOut,
} from "@/lib/api";

/** Billing settings (card B1c). Exists only on a hosted instance with Stripe
 * configured (`billing_enabled`). Stripe holds the truth: choosing a plan
 * opens Stripe Checkout, everything after that (plan change, card,
 * invoices, cancel) opens the Stripe customer portal. No prices are shown
 * here; Checkout shows what the operator set up in Stripe. */

const PLAN_LABEL: Record<PlanOut["plan"], string> = {
  free: "Free",
  starter: "Starter",
  team: "Team",
  self_hosted: "Self-hosted",
};

const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  trialing: "Trial",
  past_due: "Payment failed - Stripe retries the card",
  canceled: "Canceled",
  unpaid: "Unpaid",
  incomplete: "Payment not finished",
  incomplete_expired: "Payment not finished",
};

/** After Checkout the webhook flips the plan; poll this long for it. */
const POLL_INTERVAL_MS = 2_000;
const POLL_ATTEMPTS = 15;

const labelCls = "text-[13.5px] font-semibold";
const hintCls = "text-[12.5px] leading-[18px] text-g500";
const primaryCls =
  "inline-flex h-9 items-center rounded-md bg-accent px-4 text-[13.5px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50";
const secondaryCls =
  "inline-flex h-9 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50";

function limitText(plan: PlanOut): string {
  const max = plan.limits.max_live_jobs;
  if (max === null) return `${plan.live_jobs} live jobs, no limit`;
  return `${plan.live_jobs} of ${max} live ${max === 1 ? "job" : "jobs"}`;
}

interface Loaded {
  plan: PlanOut;
  billing: BillingOut | null;
}

async function loadBilling(): Promise<Loaded> {
  clearSharedGets(); // the plan changes behind our back (webhook)
  const plan = await companyApi.plan();
  return { plan, billing: plan.billing_enabled ? await billingApi.get() : null };
}

function BillingSettings() {
  const searchParams = useSearchParams();
  const returnedFromCheckout = searchParams.get("checkout") === "success";
  const [plan, setPlan] = useState<PlanOut | null>(null);
  const [billing, setBilling] = useState<BillingOut | null>(null);
  const [interval, setInterval_] = useState<BillingInterval>("month");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // null = not waiting; true = waiting for the webhook; false = gave up
  const [waiting, setWaiting] = useState<boolean | null>(returnedFromCheckout ? true : null);

  const show = useCallback((next: Loaded) => {
    setPlan(next.plan);
    setBilling(next.billing);
  }, []);

  useEffect(() => {
    loadBilling()
      .then(show)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load billing"),
      );
  }, [show]);

  useEffect(() => {
    if (!returnedFromCheckout) return;
    let cancelled = false;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      loadBilling()
        .then((next) => {
          if (cancelled) return;
          show(next);
          if (next.plan.plan !== "free") {
            setWaiting(null);
            window.clearInterval(timer);
          } else if (attempts >= POLL_ATTEMPTS) {
            setWaiting(false);
            window.clearInterval(timer);
          }
        })
        .catch(() => {
          // a failed poll is retried on the next tick
        });
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [returnedFromCheckout, show]);

  async function go(open: () => Promise<{ url: string }>) {
    setError(null);
    setBusy(true);
    try {
      const { url } = await open();
      window.location.assign(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach Stripe");
      setBusy(false);
    }
  }

  if (error && !plan) {
    return (
      <section className="max-w-[680px] space-y-4">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
        <SettingsTabs />
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      </section>
    );
  }

  if (!plan) {
    return (
      <section className="max-w-[680px] space-y-4">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
        <div aria-busy="true" className="h-24 animate-pulse rounded-lg bg-muted-fill" />
      </section>
    );
  }

  const paid = plan.plan === "starter" || plan.plan === "team";
  const status = billing?.status ? (STATUS_LABEL[billing.status] ?? billing.status) : null;

  return (
    <section className="max-w-[680px] space-y-4">
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
      <SettingsTabs />

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {!plan.billing_enabled ? (
        <p data-testid="billing-off" className={hintCls}>
          Billing is not enabled on this instance.
        </p>
      ) : (
        <>
          {waiting === true ? (
            <p role="status" data-testid="billing-waiting" className="text-sm text-g700">
              Payment received. Waiting for Stripe to confirm the new plan...
            </p>
          ) : null}
          {waiting === false ? (
            <p role="status" data-testid="billing-slow" className="text-sm text-g700">
              Stripe has not confirmed the new plan yet. It usually lands within a minute;
              reload this page to check.
            </p>
          ) : null}

          <div className="card space-y-2 p-4">
            <p className={labelCls}>Current plan</p>
            <p data-testid="billing-plan" className="text-[15px] font-semibold">
              {PLAN_LABEL[plan.plan]}
            </p>
            <p className={hintCls}>{limitText(plan)}</p>
            {status ? (
              <p data-testid="billing-status" className={hintCls}>
                Subscription: {status}
                {billing?.current_period_end && billing.status !== "canceled"
                  ? `, renews ${new Date(billing.current_period_end).toLocaleDateString()}`
                  : ""}
              </p>
            ) : null}
          </div>

          {paid ? (
            <div className="card space-y-3 p-4">
              <p className={hintCls}>
                Change the plan, update the card, download invoices or cancel in the Stripe
                billing portal. Canceling never closes or deletes anything: jobs stay live,
                new publishes wait until you are within the Free limit.
              </p>
              <button
                type="button"
                className={secondaryCls}
                disabled={busy || !billing?.can_manage}
                onClick={() => go(billingApi.portal)}
              >
                Manage billing
              </button>
            </div>
          ) : (
            <div className="card space-y-3 p-4">
              <div>
                <p className={labelCls}>Upgrade</p>
                <p className={hintCls}>
                  Starter allows 5 live jobs, Team has no limit. Payment and VAT are handled
                  by Stripe; prices are shown at checkout.
                </p>
              </div>
              <fieldset className="flex gap-4 text-[13px]">
                <legend className="sr-only">Billing interval</legend>
                {(["month", "year"] as const).map((value) => (
                  <label key={value} className="inline-flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="interval"
                      value={value}
                      checked={interval === value}
                      onChange={() => setInterval_(value)}
                    />
                    {value === "month" ? "Monthly" : "Yearly"}
                  </label>
                ))}
              </fieldset>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={primaryCls}
                  disabled={busy}
                  onClick={() => go(() => billingApi.checkout("starter", interval))}
                >
                  Choose Starter
                </button>
                <button
                  type="button"
                  className={primaryCls}
                  disabled={busy}
                  onClick={() => go(() => billingApi.checkout("team", interval))}
                >
                  Choose Team
                </button>
              </div>
              {billing?.can_manage ? (
                <button
                  type="button"
                  className={secondaryCls}
                  disabled={busy}
                  onClick={() => go(billingApi.portal)}
                >
                  Past invoices
                </button>
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default function BillingSettingsPage() {
  return (
    <Suspense>
      <BillingSettings />
    </Suspense>
  );
}
