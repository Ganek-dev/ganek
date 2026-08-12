"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Check } from "lucide-react";

import { ApiError, publicApplications, type ApplicationStatus } from "@/lib/api";
import { brandStyle } from "@/lib/brand";

/** Candidate status page, handoff screen 21: private magic-link page with a
 * vertical timeline (received → assessment → under review → decision) and a
 * two-step withdraw. Candidate-facing: never shows a score. */

const RED = "oklch(0.45 0.120 25)";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatDateTime(iso: string): string {
  const date = new Date(iso);
  const time = date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${formatDate(iso)}, ${time}`;
}

type StepState = "done" | "current" | "upcoming" | "muted";

function StepMarker({ state, last }: { state: StepState; last: boolean }) {
  return (
    <div className="flex w-6 shrink-0 flex-col items-center">
      {state === "done" ? (
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand text-brand-foreground">
          <Check aria-hidden className="h-[13px] w-[13px]" strokeWidth={2.5} />
        </span>
      ) : state === "current" ? (
        <span
          className="box-border flex h-6 w-6 items-center justify-center rounded-full border-2 border-brand"
          style={{ background: "color-mix(in oklab, var(--brand-primary) 8%, var(--surface))" }}
        >
          <span className="h-2 w-2 rounded-full bg-brand" />
        </span>
      ) : (
        <span className="box-border h-6 w-6 rounded-full border-2 border-edge" />
      )}
      {last ? null : (
        <span className={`min-h-[26px] w-0.5 flex-1 ${state === "done" ? "bg-brand" : "bg-edge"}`} />
      )}
    </div>
  );
}

export default function StatusPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [status, setStatus] = useState<ApplicationStatus | null>(null);
  const [invalid, setInvalid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [requestBusy, setRequestBusy] = useState(false);
  const [requestNotice, setRequestNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    publicApplications
      .status(token)
      .then(setStatus)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setInvalid(true);
        else setError(err instanceof Error ? err.message : "Something went wrong");
      });
  }, [token]);

  useEffect(load, [load]);

  const sendPrivacyRequest = useCallback(
    (kind: "data" | "deletion", companyName: string) => {
      setRequestBusy(true);
      setError(null);
      const call =
        kind === "data"
          ? publicApplications.requestData(token)
          : publicApplications.requestDeletion(token);
      call
        .then(() =>
          setRequestNotice(
            `We've sent your request to ${companyName}. They'll respond within a month.`,
          ),
        )
        .catch((err: unknown) =>
          setError(err instanceof Error ? err.message : "Request failed"),
        )
        .finally(() => setRequestBusy(false));
    },
    [token],
  );

  const withdraw = useCallback(() => {
    setBusy(true);
    setError(null);
    publicApplications
      .withdraw(token)
      .then(() => {
        setConfirming(false);
        load();
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Withdraw failed"),
      )
      .finally(() => setBusy(false));
  }, [token, load]);

  if (invalid) {
    return (
      <main className="mx-auto flex min-h-screen max-w-[560px] flex-col justify-center px-5 py-16">
        <h1 className="font-heading text-[22px] font-semibold">
          This status link is not valid
        </h1>
        <p className="mt-2 text-[15px] leading-[23px] text-g600">
          Double-check the link from your application confirmation — status links also
          expire after a while.
        </p>
      </main>
    );
  }
  if (status === null) {
    return (
      <main className="mx-auto max-w-[560px] px-6 py-16" aria-busy="true">
        <div className="h-5 w-40 animate-pulse rounded-sm bg-muted-fill" />
        <div className="mt-4 h-8 w-72 animate-pulse rounded-sm bg-muted-fill" />
        <div className="mt-10 h-64 animate-pulse rounded-lg bg-muted-fill" />
        {error ? (
          <p role="alert" className="mt-4 text-sm" style={{ color: RED }}>
            {error}
          </p>
        ) : null}
      </main>
    );
  }

  const decided = status.stage === "hired" || status.stage === "rejected";
  const withdrawn = status.stage === "withdrawn";
  const quizDone = status.quiz?.status === "completed";

  type Step = {
    key: string;
    state: StepState;
    title: string;
    titleClass?: string;
    detail: React.ReactNode;
  };
  const steps: Step[] = [
    {
      key: "received",
      state: "done",
      title: "Application received",
      detail: (
        <span className="font-mono text-[11.5px] text-g500">
          {formatDateTime(status.applied_at)}
        </span>
      ),
    },
  ];
  if (status.quiz !== null) {
    steps.push(
      quizDone
        ? {
            key: "quiz",
            state: "done",
            title: "Assessment completed",
            detail: (
              <span className="font-mono text-[11.5px] text-g500">
                {status.quiz.completed_at ? `${formatDateTime(status.quiz.completed_at)} · ` : ""}
                {status.quiz.answered} of {status.quiz.total} answered
              </span>
            ),
          }
        : {
            key: "quiz",
            state: status.quiz.status === "expired" ? "muted" : "current",
            title:
              status.quiz.status === "expired" ? "Assessment link expired" : "Assessment",
            detail: (
              <span className="text-[13.5px] leading-5 text-g600">
                {status.quiz.status === "expired"
                  ? "The team can still review your application without it."
                  : "Take the short skills assessment from the link in your email."}
              </span>
            ),
          },
    );
  }
  if (withdrawn) {
    steps.push({
      key: "withdrawn",
      state: "muted",
      title: "Withdrawn at your request",
      detail: (
        <span className="text-[13.5px] leading-5 text-g600">
          The team can no longer see your application as active.
        </span>
      ),
    });
  } else {
    steps.push({
      key: "review",
      state: decided ? "done" : "current",
      title: "Under review",
      titleClass: decided ? undefined : "text-brand",
      detail: (
        <span className="max-w-[380px] text-[13.5px] leading-5 text-g600">
          The hiring team is looking at your application
          {status.quiz !== null ? " and assessment together" : ""}. You&apos;ll hear back
          by email within two weeks of applying.
        </span>
      ),
    });
    steps.push(
      decided
        ? {
            key: "decision",
            state: "done",
            title: "Decision made — check your email",
            detail: null,
          }
        : {
            key: "decision",
            state: "upcoming",
            title: "Decision",
            detail: (
              <span className="font-mono text-[11.5px] text-g400">
                expected by {formatDate(status.decision_expected_by)}
              </span>
            ),
          },
    );
  }

  return (
    <main
      className="min-h-screen bg-surface text-foreground"
      style={brandStyle(status.brand_primary)}
    >
      <header className="border-b border-edge">
        <div className="mx-auto flex h-16 max-w-[560px] items-center justify-between px-6">
          <div className="flex items-center gap-2.5">
            <span className="flex h-[26px] w-[26px] items-center justify-center rounded-[7px] bg-brand font-heading text-sm font-bold text-brand-foreground">
              {status.company_name[0]?.toUpperCase()}
            </span>
            <span className="font-heading text-[17px] font-semibold">
              {status.company_name}
            </span>
          </div>
          <span className="overline text-[11px] text-g500">Application</span>
        </div>
      </header>

      <div className="mx-auto max-w-[560px] px-6 pt-11 pb-14">
        <div className="overline text-[11.5px] text-g500">Your application</div>
        <h1 className="mt-2.5 font-heading text-[27px] leading-[1.2] font-semibold tracking-[-0.01em]">
          {status.job_title}
        </h1>
        <div className="mt-2.5 flex flex-wrap items-center gap-3 font-mono text-xs text-g500">
          <span>{status.candidate_name}</span>
          <span aria-hidden>·</span>
          <span>applied {formatDate(status.applied_at)}</span>
          <span aria-hidden>·</span>
          <span>{status.cv_filename}</span>
        </div>

        <div className="mt-9 flex flex-col">
          {steps.map((step, index) => (
            <div key={step.key} className="flex gap-4">
              <StepMarker state={step.state} last={index === steps.length - 1} />
              <div className={index === steps.length - 1 ? "" : "pb-6"}>
                <div
                  className={
                    "text-[15px] leading-6 font-semibold " +
                    (step.state === "upcoming" || step.state === "muted"
                      ? "text-g400"
                      : (step.titleClass ?? ""))
                  }
                >
                  {step.title}
                </div>
                {step.detail ? <div className="mt-0.5">{step.detail}</div> : null}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-9 flex items-center justify-between border-t border-edge pt-5">
          <span className="font-mono text-[11px] text-g400">
            This link is private to you — no account needed.
          </span>
          {withdrawn || decided ? null : confirming ? (
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={busy}
                className="text-[13px] text-g500 hover:text-foreground"
              >
                Keep it
              </button>
              <button
                type="button"
                onClick={withdraw}
                disabled={busy}
                className="text-[13px] font-medium"
                style={{ color: RED }}
              >
                Yes, withdraw
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="text-[13px] text-g500 hover:text-foreground"
            >
              Withdraw application
            </button>
          )}
        </div>
        <div className="mt-5 border-t border-edge pt-5">
          <p className="overline text-[11px] text-g500">Your data</p>
          {withdrawn ? (
            <p className="mt-2 text-[13px] leading-[20px] text-g600">
              {`Your application is withdrawn. ${status.company_name} keeps your data for up to ${status.retention_months} months unless you request deletion.`}
            </p>
          ) : null}
          <p className="mt-2 text-[13px] leading-[20px] text-g600">
            Your data is kept for the period described in the{" "}
            <a
              href={status.privacy_url}
              className="underline hover:text-foreground"
            >
              privacy notice
            </a>
            , then deleted. You can request deletion sooner.
          </p>
          {requestNotice ? (
            <p role="status" className="mt-2.5 text-[13px] font-medium text-g700">
              {requestNotice}
            </p>
          ) : (
            <div className="mt-2.5 flex flex-wrap items-center gap-4">
              <button
                type="button"
                disabled={requestBusy}
                onClick={() => sendPrivacyRequest("data", status.company_name)}
                className="text-[13px] text-g500 underline hover:text-foreground disabled:opacity-50"
              >
                Request a copy of my data
              </button>
              <button
                type="button"
                disabled={requestBusy}
                onClick={() => sendPrivacyRequest("deletion", status.company_name)}
                className="text-[13px] text-g500 underline hover:text-foreground disabled:opacity-50"
              >
                Ask for my data to be deleted
              </button>
            </div>
          )}
        </div>
        {error ? (
          <p role="alert" className="mt-3 text-sm" style={{ color: RED }}>
            {error}
          </p>
        ) : null}
      </div>
    </main>
  );
}
