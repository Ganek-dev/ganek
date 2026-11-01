"use client";

import { useEffect, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import {
  applications,
  emailTemplates,
  type EmailKind,
  type EmailPreview,
  type EmailTemplate,
  type StageFields,
} from "@/lib/api";
import { SendAfterRadios } from "@/components/SendAfterRadios";
import { presetSendAfter, type SendAfterPreset } from "@/lib/send-after";
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
const CONFIRM_LABEL_LATER: Record<Exclude<SendAfterPreset, "now">, string> = {
  tomorrow: "Reject and email tomorrow morning",
  in_3_days: "Reject and email in 3 days",
};
const MAIL_ONLY_LABEL: Record<SendAfterPreset, string> = {
  now: "Send email",
  tomorrow: "Send email tomorrow morning",
  in_3_days: "Send email in 3 days",
};
// the candidate's own withdrawal sets "withdrew"; a recruiter never picks it
const RECRUITER_REASONS = REJECTION_REASONS.filter((reason) => reason.key !== "withdrew");
export const REASON_HELPER =
  "Internal: not emailed. Included if the candidate requests their data, so keep it factual.";

type State =
  | { kind: "loading" }
  | { kind: "ready"; preview: EmailPreview }
  | { kind: "error" };

/** The server's answer for one template choice; another choice on screen
 * renders as loading until its own answer lands. */
type Fetched = { templateId: string; state: State };
const PREVIEW_DEBOUNCE_MS = 300;
export const BUILTIN_TEMPLATE = "builtin";
export const EDIT_HELPER =
  "Edited for this send. The link and the privacy footer are always added by Ganek.";

export function StageEmailDialog({
  open,
  applicationId,
  candidateName,
  stage,
  email: emailProp,
  defaultPreset = "now",
  mailOnly = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  applicationId: string;
  candidateName: string;
  stage: Stage;
  /** Whether confirming also emails the candidate (the panel checkbox). */
  email: boolean;
  /** Preselected "When" option for a rejection email. */
  defaultPreset?: SendAfterPreset;
  /** Mail without a stage move (already rejected): no reason or note, the
   * email is always on. */
  mailOnly?: boolean;
  onConfirm: (fields: StageFields) => void;
  onCancel: () => void;
}) {
  const email = emailProp || mailOnly;
  const [preset, setPreset] = useState<SendAfterPreset>(defaultPreset);
  const showWhen = email && stage === "rejected";
  const [reason, setReason] = useState<RejectionReason | "">("");
  const [note, setNote] = useState("");
  // the workspace's templates for this kind (PR 3); null until listed, [] when
  // only the Ganek default exists (the select stays hidden then)
  const [templates, setTemplates] = useState<EmailTemplate[] | null>(null);
  const [templateId, setTemplateId] = useState(BUILTIN_TEMPLATE);
  const [fetched, setFetched] = useState<Fetched | null>(null);
  // "Edit this email" (PR 4): the recruiter's literal text for this send
  // only, prefilled from the rendered preview; null while the template text
  // is used as is
  const [edit, setEdit] = useState<{ subject: string; body: string } | null>(null);
  const kind = KIND_FOR[stage];

  useEffect(() => {
    if (!open || !email) return;
    let cancelled = false;
    emailTemplates
      .list()
      .then((data) => {
        if (cancelled) return;
        const own = data.kinds.find((entry) => entry.kind === kind)?.templates ?? [];
        setTemplates(own);
        setTemplateId(own.find((t) => t.is_default)?.id ?? BUILTIN_TEMPLATE);
      })
      .catch(() => {
        // the picker is a convenience: without the list the default applies
        if (!cancelled) setTemplates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, email, kind]);

  const hasTemplates = templates !== null && templates.length > 0;
  // without custom templates nothing is sent: the server applies the default
  const chosen = hasTemplates ? templateId : undefined;

  useEffect(() => {
    if (!open || !email || templates === null) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      applications
        .emailPreview(applicationId, kind, chosen)
        .then((preview) => {
          if (!cancelled) setFetched({ templateId, state: { kind: "ready", preview } });
        })
        .catch(() => {
          if (!cancelled) setFetched({ templateId, state: { kind: "error" } });
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, email, templates, applicationId, kind, chosen, templateId]);

  const state: State =
    fetched !== null && fetched.templateId === templateId ? fetched.state : { kind: "loading" };

  const editBlank = edit !== null && (!edit.subject.trim() || !edit.body.trim());
  const confirm = () =>
    onConfirm({
      rejectionReason: reason || null,
      rejectionNote: note.trim() || null,
      ...(showWhen ? { sendAfter: presetSendAfter(preset) } : {}),
      ...(hasTemplates ? { templateId } : {}),
      ...(edit ? { subject: edit.subject.trim(), body: edit.body.trim() } : {}),
    });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogTitle>
          {mailOnly
            ? `Send rejection email to ${candidateName}`
            : email
              ? `Email to ${candidateName}`
              : `${CONFIRM_LABEL_SILENT[stage]} ${candidateName}`}
        </DialogTitle>
        <DialogDescription>
          {email ? "This is the email the candidate receives when you confirm." : "No email will be sent."}
        </DialogDescription>
        {email ? (
        <div className="mt-3">
          {hasTemplates ? (
            <label className="mb-3 block text-[13px] font-medium text-g700">
              Template
              <select
                value={templateId}
                disabled={edit !== null}
                title={edit ? "Leave the edit to pick a template" : undefined}
                onChange={(e) => setTemplateId(e.target.value)}
                className="mt-1 block h-8 w-full rounded-md border border-edge bg-surface px-2 text-[13px] font-normal text-foreground disabled:opacity-60"
              >
                <option value={BUILTIN_TEMPLATE}>Ganek default</option>
                {templates?.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {edit ? (
            <div className="space-y-2">
              <label className="block text-[13px] font-medium text-g700">
                Subject
                <input
                  type="text"
                  value={edit.subject}
                  maxLength={200}
                  onChange={(e) => setEdit({ ...edit, subject: e.target.value })}
                  className="mt-1 block h-8 w-full rounded-md border border-edge bg-surface px-2 text-[13px] font-normal text-foreground"
                />
              </label>
              <label className="block text-[13px] font-medium text-g700">
                Body
                <textarea
                  value={edit.body}
                  maxLength={10000}
                  rows={8}
                  onChange={(e) => setEdit({ ...edit, body: e.target.value })}
                  className="mt-1 block w-full rounded-md border border-edge bg-surface px-2 py-1.5 font-mono text-[12px] leading-[18px] font-normal text-foreground"
                />
              </label>
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11.5px] text-g500">{EDIT_HELPER}</p>
                <button
                  type="button"
                  onClick={() => setEdit(null)}
                  className="shrink-0 text-[12px] text-g600 underline hover:text-accent"
                >
                  Use the template text
                </button>
              </div>
            </div>
          ) : state.kind === "loading" ? (
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
              <button
                type="button"
                onClick={() =>
                  setEdit({ subject: state.preview.subject, body: state.preview.body })
                }
                className="mt-2 text-[12px] text-g600 underline hover:text-accent"
              >
                Edit this email
              </button>
            </>
          )}
        </div>
        ) : null}
        {showWhen ? (
          <div className="mt-4">
            <SendAfterRadios value={preset} onChange={setPreset} />
          </div>
        ) : null}
        {stage === "rejected" && !mailOnly ? (
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
            disabled={(email && state.kind === "loading") || editBlank}
            className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            {mailOnly
              ? MAIL_ONLY_LABEL[preset]
              : email
                ? stage === "rejected" && preset !== "now"
                  ? CONFIRM_LABEL_LATER[preset]
                  : CONFIRM_LABEL[stage]
                : CONFIRM_LABEL_SILENT[stage]}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
