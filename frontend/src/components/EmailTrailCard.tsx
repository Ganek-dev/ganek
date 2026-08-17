"use client";

import { useEffect, useState } from "react";

import { applications, type EmailDelivery } from "@/lib/api";

/** Delivery trail for an applicant (M5.7 H4): the emails this application
 * depends on and whether they actually went out. Renders nothing while the
 * trail is empty — most panels predate the outbox and silence beats an
 * empty card. */

const KIND_LABELS: Record<string, string> = {
  application_received: "Application confirmation",
  quiz_invite: "Assessment invite",
  quiz_reminder: "Assessment reminder",
  stage_advance: "Advance update",
  rejection: "Rejection",
  interview_invite: "Interview booking link",
  interview_cancelled: "Interview cancellation",
};

function relativeTime(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

const STATUS_META: Record<
  EmailDelivery["status"],
  { dot: string; label: (row: EmailDelivery) => string }
> = {
  sent: { dot: "bg-emerald-500", label: (row) => relativeTime(row.sent_at ?? row.created_at) },
  queued: {
    dot: "bg-amber-500",
    label: (row) => (row.attempts > 0 ? `retrying (attempt ${row.attempts})` : "queued"),
  },
  failed: { dot: "bg-red-500", label: () => "failed" },
};

export function EmailTrailCard({ applicationId }: { applicationId: string }) {
  const [rows, setRows] = useState<EmailDelivery[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    applications
      .emails(applicationId)
      .then((list) => {
        if (!cancelled) setRows(list);
      })
      .catch(() => {
        if (!cancelled) setRows([]); // decoration: an error must not break the panel
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  if (rows === null || rows.length === 0) return null;
  const failed = rows.filter((row) => row.status === "failed").length;

  return (
    <div className="card mt-5 p-4">
      <div className="flex items-center gap-2">
        <p className="text-[13px] font-semibold">Email</p>
        {failed > 0 ? (
          <span className="inline-flex h-5 items-center rounded-full bg-red-600/10 px-2 font-mono text-[11px] font-medium text-red-600 dark:text-red-400">
            {failed} failed
          </span>
        ) : null}
      </div>
      <ul className="mt-2.5 space-y-1.5">
        {rows.map((row) => {
          const meta = STATUS_META[row.status];
          return (
            <li key={row.id} className="flex items-baseline gap-2 text-[13px]">
              <span
                aria-hidden
                className={`inline-block h-1.5 w-1.5 shrink-0 self-center rounded-full ${meta.dot}`}
              />
              <span className="text-g700">{KIND_LABELS[row.kind] ?? row.kind}</span>
              <span className="ml-auto shrink-0 font-mono text-[11px] text-g500">
                {meta.label(row)}
              </span>
            </li>
          );
        })}
      </ul>
      {failed > 0 ? (
        <p className="mt-2 text-[11.5px] text-red-600 dark:text-red-400">
          {rows.find((row) => row.status === "failed")?.last_error === "SMTP not configured"
            ? "Email is not configured on this instance — nothing is being delivered."
            : "Delivery failed after retries — check your SMTP settings and use the test send on Settings → Privacy."}
        </p>
      ) : null}
    </div>
  );
}
