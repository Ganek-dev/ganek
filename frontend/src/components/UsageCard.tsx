"use client";

import { useEffect, useState } from "react";

import { companyApi, type UsageOut } from "@/lib/api";

/** Dashboard card with the per-tenant counters from GET /company/usage
 * (card B3: a new multi-mode company sees its limits in the first
 * session). Multi mode only: on a single-company instance the operator
 * set these guards themselves and the admin banner already warns at 80%.
 * A guard at 0 is off and shows as "no limit". Any load error renders
 * nothing; the card must never break the dashboard. */

interface Meter {
  label: string;
  used: number;
  limit: number;
}

function meters(usage: UsageOut): Meter[] {
  return [
    { label: "Open jobs", used: usage.active_jobs, limit: usage.active_jobs_limit },
    {
      label: "Applications this hour",
      used: usage.applications_this_hour,
      limit: usage.applications_per_hour_limit,
    },
    {
      label: "Candidate emails today",
      used: usage.emails_today,
      limit: usage.emails_per_day_limit,
    },
  ];
}

function fillColor(used: number, limit: number): string {
  const ratio = used / limit;
  if (ratio >= 1) return "var(--danger)";
  if (ratio >= 0.8) return "var(--warn)";
  return "var(--accent)";
}

export function UsageCard() {
  const [usage, setUsage] = useState<UsageOut | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const company = await companyApi.get();
        if (company.mode !== "multi") return;
        const data = await companyApi.usage();
        if (!cancelled) setUsage(data);
      } catch {
        // leave usage null; the dashboard renders fine without the card
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (usage === null) return null;

  return (
    <div className="card px-5 py-[18px]" data-testid="usage-card">
      <div className="flex items-baseline justify-between">
        <h2 className="font-heading text-[15px] font-semibold">Usage and limits</h2>
        <span className="font-mono text-[11px] text-g500">
          applications reset hourly · emails daily
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {meters(usage).map((meter) => (
          <div key={meter.label}>
            <dt className="text-xs text-g500">{meter.label}</dt>
            <dd className="mt-1 font-mono text-[13px] font-medium text-strong">
              {meter.limit > 0 ? `${meter.used} of ${meter.limit}` : `${meter.used}, no limit`}
            </dd>
            {meter.limit > 0 ? (
              <div
                role="progressbar"
                aria-label={meter.label}
                aria-valuemin={0}
                aria-valuemax={meter.limit}
                aria-valuenow={Math.min(meter.used, meter.limit)}
                className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted-fill"
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(100, (meter.used / meter.limit) * 100)}%`,
                    background: fillColor(meter.used, meter.limit),
                  }}
                />
              </div>
            ) : null}
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[12px] text-g500">
        Past a limit, candidates see a &quot;try again later&quot; message on apply and new
        jobs cannot be published until one closes.
      </p>
    </div>
  );
}
