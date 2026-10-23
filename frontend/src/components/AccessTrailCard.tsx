"use client";

import { useEffect, useState } from "react";

import { applications, type AccessEntry } from "@/lib/api";
import { relativeTime } from "@/lib/time";

/** Who looked at this candidate (read-access audit trail), admins only:
 * the endpoint answers 403 for members and the card simply stays hidden. */

const ACTION_LABELS: Record<string, string> = {
  view: "opened the profile",
  cv_download: "opened the CV",
  quiz_answers: "viewed the quiz answers",
  dsar_export: "exported the data bundle",
};

function actorName(entry: AccessEntry): string {
  if (entry.api_key_name) return `API key ${entry.api_key_name}`;
  return entry.actor_label || entry.actor_email || "A former teammate";
}

export function AccessTrailCard({ applicationId, now }: { applicationId: string; now: Date }) {
  const [rows, setRows] = useState<AccessEntry[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    applications
      .accessLog(applicationId)
      .then((list) => {
        if (!cancelled) setRows(list);
      })
      .catch(() => {
        if (!cancelled) setRows([]); // members get 403; decoration never breaks the panel
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  if (rows === null || rows.length === 0) return null;

  return (
    <div className="card mt-5 p-4">
      <p className="text-[13px] font-semibold">Access</p>
      <p className="mt-0.5 text-[12px] text-g500">
        Who looked at this candidate. Repeats within ten minutes count once.
      </p>
      <ul className="mt-2.5 space-y-1.5">
        {rows.map((row) => (
          <li key={row.id} className="flex items-baseline gap-2 text-[13px]">
            <span className="text-g700">
              {actorName(row)} {ACTION_LABELS[row.action] ?? row.action}
            </span>
            <span className="ml-auto shrink-0 font-mono text-[11px] text-g500">
              {relativeTime(row.created_at, now)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
