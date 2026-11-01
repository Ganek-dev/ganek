"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { review, type ReviewApplicationListItem } from "@/lib/api";
import { formatDateTime, formatDay } from "@/lib/time";

/** The reviewer's candidate list (scorecards spec 5.2). Status line: the
 * reviewer's own scorecard first, then the interview. No pass/fail reading. */

function statusLine(item: ReviewApplicationListItem): string {
  if (item.scorecard_state === "open") return "Scorecard due";
  if (item.scorecard_state === "submitted")
    return item.scorecard_submitted_at
      ? `Submitted ${formatDay(item.scorecard_submitted_at)}`
      : "Submitted";
  if (item.scorecard_state === "declined") return "Declined";
  if (item.interview_start) return `Interview ${formatDateTime(item.interview_start)}`;
  return item.stage_label;
}

export default function ReviewListPage() {
  const [items, setItems] = useState<ReviewApplicationListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    review
      .list()
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load candidates");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1 className="font-heading text-[22px] font-semibold">Your candidates</h1>
      {error ? (
        <p role="alert" className="mt-4 text-[13.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : items === null ? (
        <ul className="mt-4 space-y-2" aria-busy="true">
          {[0, 1, 2].map((n) => (
            <li
              key={n}
              data-testid="review-skeleton"
              className="h-[68px] animate-pulse rounded-md bg-muted-fill"
            />
          ))}
        </ul>
      ) : items.length === 0 ? (
        <p className="mt-4 text-[14px] text-g600">Nothing waiting on you.</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {items.map((item) => (
            <li key={item.application_id}>
              <Link
                href={`/review/${item.application_id}`}
                className="card flex items-center gap-3 px-4 py-3 hover:border-accent"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-semibold">
                    {item.candidate_name}
                  </span>
                  <span className="block truncate text-[12.5px] text-g600">{item.job_title}</span>
                </span>
                <span className="shrink-0 text-[12.5px] text-g600">{statusLine(item)}</span>
                <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-g500" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
