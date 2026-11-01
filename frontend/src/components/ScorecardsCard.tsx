"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Check, UserPlus } from "lucide-react";

import {
  api,
  RECOMMENDATION_LABELS,
  scorecards,
  team,
  waitingCopy,
  type Scorecard,
  type TeamUser,
  type UserOut,
} from "@/lib/api";
import { relativeTime } from "@/lib/time";

import { ScorecardForm } from "./ScorecardForm";
import { Avatar, Chip, SubmittedBody } from "./ScorecardParts";

/** Scorecards on an applicant (candidate panel, between the interview and the
 * quiz block). Self-contained: fetches its own rows, the current user and
 * (on demand) the team. Dismissed rows are history and are not listed; the
 * recommendation chip is deliberately neutral (no red/green scoring). */

export function ScorecardsCard({
  applicationId,
  autoOpen = false,
}: {
  applicationId: string;
  autoOpen?: boolean;
}) {
  const [rows, setRows] = useState<Scorecard[]>([]);
  const [me, setMe] = useState<UserOut | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [members, setMembers] = useState<TeamUser[] | null>(null);
  const [picking, setPicking] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const formRef = useRef<HTMLDivElement>(null);
  const hasForm = loaded && rows.some((r) => r.state === "open" && r.reviewer_user_id === me?.id);

  // ?scorecard=1 (the queue link): bring the inline form into view once.
  useEffect(() => {
    if (autoOpen && hasForm) formRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [autoOpen, hasForm]);

  // The team list backs both the picker and the "Request again" guard (an
  // anonymised teammate keeps their id but is inactive, and would 404).
  useEffect(() => {
    let cancelled = false;
    team
      .list()
      .then((list) => {
        if (!cancelled) setMembers(list);
      })
      .catch(() => {
        // stays null: the picker retries on open, "Request again" stays hidden
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const reload = useCallback(async () => {
    setRows(await scorecards.list(applicationId));
  }, [applicationId]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([scorecards.list(applicationId), api.me()])
      .then(([list, user]) => {
        if (cancelled) return;
        setRows(list);
        setMe(user);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load scorecards");
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  async function act(action: () => Promise<unknown>, fallback: string) {
    setError(null);
    try {
      await action();
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    }
  }

  async function openPicker() {
    setPicking(true);
    if (members !== null) return;
    try {
      setMembers(await team.list());
    } catch (err) {
      setPicking(false);
      setError(err instanceof Error ? err.message : "Failed to load team");
    }
  }

  if (!loaded) {
    return (
      <div className="card mt-5 p-4">
        <div aria-busy="true" className="h-16 animate-pulse rounded-md bg-muted-fill" />
      </div>
    );
  }

  const visible = rows.filter((row) => row.state !== "dismissed");
  const mine = me ? visible.find((r) => r.state === "open" && r.reviewer_user_id === me.id) : null;
  // Submitted rows would 409 on a new request; open rows are already waiting.
  const taken = new Set(
    visible
      .filter((r) => r.state === "open" || r.state === "submitted")
      .map((r) => r.reviewer_user_id),
  );
  const activeIds = new Set((members ?? []).filter((m) => m.is_active).map((m) => m.id));
  const candidates = (members ?? []).filter(
    (member) => member.is_active && member.id !== me?.id && !taken.has(member.id),
  );
  const showForm = mine ?? null;

  return (
    <div className="card mt-5 p-4">
      <div className="flex items-center gap-2">
        <p className="text-[13px] font-semibold">Scorecards</p>
        <span className="inline-flex h-5 items-center rounded-full border border-edge bg-muted-fill px-2 font-mono text-[11px] font-medium text-g600">
          {visible.length}
        </span>
        <button
          type="button"
          onClick={() => void openPicker()}
          className="ml-auto inline-flex h-7 items-center gap-1 rounded-md border border-edge bg-surface px-2 text-[12px] font-medium hover:bg-muted-fill"
        >
          <UserPlus aria-hidden className="h-3.5 w-3.5" />
          Request
        </button>
      </div>

      {picking ? (
        <div className="mt-3">
          <select
            aria-label="Request a scorecard from"
            value=""
            disabled={members === null}
            onChange={(event) => {
              const id = event.target.value;
              if (!id) return;
              setPicking(false);
              void act(() => scorecards.requestFrom(applicationId, id), "Failed to request");
            }}
            className="h-8 w-full rounded-md border border-edge bg-surface px-2 text-[13px] outline-none focus:border-accent"
          >
            <option value="">
              {members === null
                ? "Loading team"
                : candidates.length === 0
                  ? "No one left to ask"
                  : "Choose a teammate"}
            </option>
            {candidates.map((member) => (
              <option key={member.id} value={member.id}>
                {member.display_label ?? member.display_name ?? member.email}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {showForm ? (
        <div ref={formRef} className="mt-3 rounded-md border border-edge p-3">
          <p className="mb-3 text-[13px] font-medium">Your scorecard</p>
          <ScorecardForm
            criteria={showForm.criteria}
            submitLabel="Submit scorecard"
            onSubmit={async (body) => {
              await scorecards.submit(applicationId, body);
              await reload();
            }}
            onDecline={async () => {
              await scorecards.decline(applicationId);
              await reload();
            }}
          />
        </div>
      ) : null}

      {visible.filter((r) => r !== showForm).length > 0 ? (
        <ul className="mt-3 space-y-2">
          {visible
            .filter((r) => r !== showForm)
            .map((row) => (
              <li key={row.id} className="rounded-md border border-edge px-3 py-2">
                {editingId === row.id && row.state === "submitted" ? (
                  <ScorecardForm
                    criteria={row.criteria}
                    initial={row}
                    submitLabel="Save changes"
                    onSubmit={async (body) => {
                      await scorecards.submit(applicationId, body);
                      setEditingId(null);
                      await reload();
                    }}
                  />
                ) : (
                  <>
                    <div className="flex items-center gap-2">
                      <Avatar label={row.reviewer_label} />
                      <span className="text-[13px] font-medium">{row.reviewer_label}</span>
                      {row.state === "submitted" && row.recommendation ? (
                        <Chip>{RECOMMENDATION_LABELS[row.recommendation]}</Chip>
                      ) : null}
                      {row.state === "open" ? <Chip>Waiting</Chip> : null}
                      {row.state === "declined" ? <Chip>Declined</Chip> : null}
                      {row.state === "submitted" ? (
                        <span className="ml-auto flex items-center gap-2 text-[11.5px] text-g500">
                          <Check aria-hidden className="h-3 w-3" />
                          {row.submitted_at ? relativeTime(row.submitted_at) : null}
                          {row.edited ? " · edited" : null}
                          {row.can_edit ? (
                            <button
                              type="button"
                              onClick={() => setEditingId(row.id)}
                              className="font-medium text-foreground hover:underline"
                            >
                              Edit
                            </button>
                          ) : null}
                        </span>
                      ) : null}
                    </div>
                    {row.state === "open" ? (
                      <p className="mt-1 flex items-center justify-between gap-3 text-[12.5px] text-g600">
                        {waitingCopy(row.reviewer_label, row.waiting_days, row.due_from)}
                        <button
                          type="button"
                          onClick={() =>
                            void act(() => scorecards.dismiss(row.id), "Failed to dismiss")
                          }
                          className="text-g500 hover:underline"
                        >
                          Dismiss
                        </button>
                      </p>
                    ) : null}
                    {row.state === "declined" ? (
                      <p className="mt-1 flex items-center justify-between gap-3 text-[12.5px] text-g600">
                        Declined by {row.reviewer_label}
                        {activeIds.has(row.reviewer_user_id ?? "") && row.reviewer_user_id !== me?.id ? (
                          <button
                            type="button"
                            onClick={() =>
                              void act(
                                () => scorecards.requestFrom(applicationId, row.reviewer_user_id!),
                                "Failed to request",
                              )
                            }
                            className="text-g500 hover:underline"
                          >
                            Request again
                          </button>
                        ) : null}
                      </p>
                    ) : null}
                    {row.state === "submitted" ? <SubmittedBody row={row} /> : null}
                  </>
                )}
              </li>
            ))}
        </ul>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}
