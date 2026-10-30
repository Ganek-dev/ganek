"use client";

import { useEffect, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import {
  applications,
  type EmailKind,
  type EmailPreview,
  type RejectionFields,
} from "@/lib/api";
import { REJECTION_REASONS, type RejectionReason } from "@/lib/rejection-reasons";

/** Confirm step before a stage move (card "Candidate emails", PR 1 + 2).
 * With `email` the rendered subject and text for this candidate, exactly
 * what the sender delivers; the preview failing never blocks the move: the
 * server renders the same email anyway. A rejection also takes the optional
 * internal reason and note (PR 2), which never reach the candidate. The
 * parent re-keys the dialog per opening so it mounts fresh (no state reset
 * in effects). */

type Stage = "interview" | "rejected";

const KIND_FOR: Record<Stage, EmailKind> = { interview: "stage_advance", rejected: "rejection" };
const CONFIRM_LABEL: Record<Stage, string> = {
  interview: "Move to Interview and send email",
  rejected: "Reject and send email",
};
const CONFIRM_LABEL_SILENT: Record<Stage, string> = {
  interview: "Move to Interview",
  rejected: "Reject",
};
// the candidate's own withdrawal sets "withdrew"; a recruiter never picks it
const RECRUITER_REASONS = REJECTION_REASONS.filter((reason) => reason.key !== "withdrew");
export const REASON_HELPER =
  "Internal: not emailed. Included if the candidate requests their data, so keep it factual.";

type State =
  | { kind: "loading" }
  | { kind: "ready"; preview: EmailPreview }
  | { kind: "error" };

export function StageEmailDialog({
  open,
  applicationId,
  candidateName,
  stage,
  email,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  applicationId: string;
  candidateName: string;
  stage: Stage;
  /** Whether confirming also emails the candidate (the panel checkbox). */
  email: boolean;
  onConfirm: (fields: RejectionFields) => void;
  onCancel: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [reason, setReason] = useState<RejectionReason | "">("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!open || !email) return;
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
  }, [open, email, applicationId, stage]);

  const confirm = () =>
    onConfirm({ rejectionReason: reason || null, rejectionNote: note.trim() || null });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogTitle>
          {email ? `Email to ${candidateName}` : `${CONFIRM_LABEL_SILENT[stage]} ${candidateName}`}
        </DialogTitle>
        <DialogDescription>
          {email ? "This is the email the candidate receives when you confirm." : "No email will be sent."}
        </DialogDescription>
        {email ? (
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
        ) : null}
        {stage === "rejected" ? (
          <div className="mt-4 space-y-2">
            <label className="block text-[13px] font-medium text-g700">
              Reason (internal, optional)
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value as RejectionReason | "")}
                className="mt-1 block h-8 w-full rounded-md border border-edge bg-surface px-2 text-[13px] font-normal text-foreground"
              >
                <option value="">No reason recorded</option>
                {RECRUITER_REASONS.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <textarea
              aria-label="Internal note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Internal note (optional)"
              maxLength={1000}
              rows={2}
              className="block w-full rounded-md border border-edge bg-surface px-2 py-1.5 text-[13px] text-foreground placeholder:text-g500"
            />
            <p className="text-[11.5px] text-g500">{REASON_HELPER}</p>
          </div>
        ) : null}
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
            onClick={confirm}
            disabled={email && state.kind === "loading"}
            className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            {email ? CONFIRM_LABEL[stage] : CONFIRM_LABEL_SILENT[stage]}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
