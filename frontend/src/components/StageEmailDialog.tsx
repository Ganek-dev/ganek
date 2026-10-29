"use client";

import { useEffect, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { applications, type EmailKind, type EmailPreview } from "@/lib/api";

/** Confirm step before a stage move emails the candidate (card "Candidate
 * emails", PR 1): the rendered subject and text for this candidate, exactly
 * what the sender delivers. The preview failing never blocks the move: the
 * server renders the same email anyway. The parent re-keys the dialog per
 * opening so it mounts in the loading state (no state reset in effects). */

type Stage = "interview" | "rejected";

const KIND_FOR: Record<Stage, EmailKind> = { interview: "stage_advance", rejected: "rejection" };
const CONFIRM_LABEL: Record<Stage, string> = {
  interview: "Move to Interview and send email",
  rejected: "Reject and send email",
};

type State =
  | { kind: "loading" }
  | { kind: "ready"; preview: EmailPreview }
  | { kind: "error" };

export function StageEmailDialog({
  open,
  applicationId,
  candidateName,
  stage,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  applicationId: string;
  candidateName: string;
  stage: Stage;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    applications
      .emailPreview(applicationId, KIND_FOR[stage])
      .then((preview) => {
        if (!cancelled) setState({ kind: "ready", preview });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [open, applicationId, stage]);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogTitle>Email to {candidateName}</DialogTitle>
        <DialogDescription>
          This is the email the candidate receives when you confirm.
        </DialogDescription>
        <div className="mt-3">
          {state.kind === "loading" ? (
            <div aria-busy="true" aria-label="Loading preview" className="space-y-2">
              <div className="h-5 w-64 animate-pulse rounded-sm bg-muted-fill" />
              <div className="h-40 animate-pulse rounded-md bg-muted-fill" />
            </div>
          ) : state.kind === "error" ? (
            <p role="alert" className="text-sm text-g600">
              Preview unavailable. The email is still sent when you confirm.
            </p>
          ) : (
            <>
              <p className="text-[13px] text-g600">
                Subject: <span className="font-medium text-foreground">{state.preview.subject}</span>
              </p>
              <pre
                data-testid="stage-email-text"
                className="mt-2 max-h-72 overflow-auto rounded-md border border-edge bg-muted-fill p-3 font-mono text-[12px] leading-[18px] whitespace-pre-wrap text-g700"
              >
                {state.preview.text}
              </pre>
            </>
          )}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={state.kind === "loading"}
            className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            {CONFIRM_LABEL[stage]}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
