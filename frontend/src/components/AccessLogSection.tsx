"use client";

import { useEffect, useState } from "react";

import { accessLogApi, team, type AccessLogFilters, type AccessLogRow, type TeamUser } from "@/lib/api";
import { relativeTime } from "@/lib/time";

/** Company-wide read-access log (Settings > Privacy), admins only: who
 * opened which candidate, filtered by teammate and action, newest first,
 * with the same filter as a CSV file. The endpoint answers 403 for
 * members and the section then stays hidden. */

const PAGE = 50;

const ACTION_LABELS: Record<string, string> = {
  view: "opened the profile",
  cv_download: "opened the CV",
  quiz_answers: "viewed the quiz answers",
  dsar_export: "exported the data bundle",
};

function actorName(row: AccessLogRow): string {
  if (row.api_key_name) return `API key ${row.api_key_name}`;
  return row.actor_label || row.actor_email || "Removed teammate";
}

const selectCls =
  "h-8 rounded-md border border-edge bg-surface px-2 text-[13px] text-g700 disabled:opacity-50";

export function AccessLogSection({ now }: { now: Date }) {
  const [teammates, setTeammates] = useState<TeamUser[]>([]);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [rows, setRows] = useState<AccessLogRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    team
      .list()
      .then(setTeammates)
      .catch(() => setTeammates([]));
  }, []);

  const filters: AccessLogFilters = {
    ...(actor ? { actor_user_id: actor } : {}),
    ...(action ? { action } : {}),
  };
  const filterKey = `${actor}|${action}`;

  useEffect(() => {
    let cancelled = false;
    accessLogApi
      .list({ ...filters, limit: PAGE, offset })
      .then((page) => {
        if (cancelled) return;
        setTotal(page.total);
        setRows((prev) => (offset === 0 || prev === null ? page.items : [...prev, ...page.items]));
      })
      .catch(() => {
        if (!cancelled) setHidden(true); // members: 403
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, offset]);

  if (hidden) return null;

  function changeFilter(setter: (value: string) => void, value: string) {
    setBusy(true);
    setter(value);
    setOffset(0);
  }

  return (
    <div className="card space-y-3 p-4">
      <div>
        <p className="text-[13.5px] font-semibold">Access log</p>
        <p className="mt-0.5 text-[12.5px] leading-[18px] text-g500">
          Who opened which candidate: profile, CV, quiz answers or data bundle. Repeats within
          ten minutes count once; the applicant list is not logged.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Teammate"
          value={actor}
          disabled={busy}
          onChange={(event) => changeFilter(setActor, event.target.value)}
          className={selectCls}
        >
          <option value="">Everyone</option>
          {teammates.map((user) => (
            <option key={user.id} value={user.id}>
              {user.display_label || user.email}
            </option>
          ))}
        </select>
        <select
          aria-label="Action"
          value={action}
          disabled={busy}
          onChange={(event) => changeFilter(setAction, event.target.value)}
          className={selectCls}
        >
          <option value="">Any action</option>
          <option value="view">Opened the profile</option>
          <option value="cv_download">Opened the CV</option>
          <option value="quiz_answers">Viewed the quiz answers</option>
          <option value="dsar_export">Exported the data bundle</option>
        </select>
        <a
          href={accessLogApi.exportUrl(filters)}
          download
          className="ml-auto inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill"
        >
          Download CSV
        </a>
      </div>
      {rows === null ? (
        <div aria-busy="true" className="space-y-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-6 animate-pulse rounded-sm bg-muted-fill" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-g500">Nobody has opened a candidate yet.</p>
      ) : (
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left font-mono text-[11px] tracking-[0.08em] text-g500 uppercase">
              <th className="py-1 pr-3 font-medium">Who</th>
              <th className="py-1 pr-3 font-medium">What</th>
              <th className="py-1 pr-3 font-medium">Candidate</th>
              <th className="py-1 pr-3 font-medium">Job</th>
              <th className="py-1 text-right font-medium">When</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-divider">
                <td className="py-1.5 pr-3 text-g700">{actorName(row)}</td>
                <td className="py-1.5 pr-3 text-g600">{ACTION_LABELS[row.action] ?? row.action}</td>
                <td className="py-1.5 pr-3 text-g700">{row.candidate_name}</td>
                <td className="py-1.5 pr-3 text-g600">{row.job_title}</td>
                <td className="py-1.5 text-right font-mono text-[11px] text-g500">
                  {relativeTime(row.created_at, now)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rows !== null && rows.length < total ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setOffset(rows.length);
          }}
          className="inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50"
        >
          Show more
        </button>
      ) : null}
    </div>
  );
}
