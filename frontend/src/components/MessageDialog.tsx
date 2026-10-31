"use client";

import { useEffect, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { applications, type EmailPreview, type MessageInput } from "@/lib/api";

/** A one-off message to a candidate from the panel (card "Candidate
 * emails", PR 4): subject and body as typed, a live preview of the mail as
 * the candidate receives it (the server renders it, nothing is queued), and
 * Send. Replies land in the sender's own inbox (Reply-To). The parent
 * re-keys the dialog per opening so it mounts fresh. */

const PREVIEW_DEBOUNCE_MS = 400;
export const PREVIEW_ERROR = "Preview unavailable. The message is still sent when you confirm.";

type PreviewState =
  | { kind: "loading" }
  | { kind: "ready"; preview: EmailPreview }
  | { kind: "error" };

/** The server's answer for one (subject, body); other text on screen renders
 * as loading until its own answer lands. */
type Fetched = { key: string; state: PreviewState };

export function MessageDialog({
  open,
  applicationId,
  candidateName,
  onSend,
  onCancel,
}: {
  open: boolean;
  applicationId: string;
  candidateName: string;
  /** Resolves to an error message to show, or null when the message went out. */
  onSend: (fields: MessageInput) => Promise<string | null>;
  onCancel: () => void;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [fetched, setFetched] = useState<Fetched | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const complete = subject.trim().length > 0 && body.trim().length > 0;
  const key = `${subject}\u0000${body}`;

  useEffect(() => {
    if (!open || !complete) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      applications
        .messagePreview(applicationId, { subject, body })
        .then((preview) => {
          if (!cancelled) setFetched({ key, state: { kind: "ready", preview } });
        })
        .catch(() => {
          if (!cancelled) setFetched({ key, state: { kind: "error" } });
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, complete, applicationId, subject, body, key]);

  const state: PreviewState | null = !complete
    ? null
    : fetched !== null && fetched.key === key
      ? fetched.state
      : { kind: "loading" };

  async function send() {
    setSending(true);
    setError(null);
    try {
      const result = await onSend({ subject: subject.trim(), body: body.trim() });
      if (result !== null) setError(result);
    } finally {
      setSending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogTitle>{`Message to ${candidateName}`}</DialogTitle>
        <DialogDescription>Replies go to your own inbox.</DialogDescription>
        <div className="mt-3 space-y-2">
          <label className="block text-[13px] font-medium text-g700">
            Subject
            <input
              type="text"
              value={subject}
              maxLength={200}
              onChange={(e) => setSubject(e.target.value)}
              className="mt-1 block h-8 w-full rounded-md border border-edge bg-surface px-2 text-[13px] font-normal text-foreground"
            />
          </label>
          <label className="block text-[13px] font-medium text-g700">
            Body
            <textarea
              value={body}
              maxLength={10000}
              rows={8}
              onChange={(e) => setBody(e.target.value)}
              className="mt-1 block w-full rounded-md border border-edge bg-surface px-2 py-1.5 font-mono text-[12px] leading-[18px] font-normal text-foreground"
            />
          </label>
          {state === null ? null : state.kind === "loading" ? (
            <div aria-busy="true" aria-label="Loading preview" className="space-y-2">
              <div className="h-5 w-64 animate-pulse rounded-sm bg-muted-fill" />
              <div className="h-24 animate-pulse rounded-md bg-muted-fill" />
            </div>
          ) : state.kind === "error" ? (
            <p className="text-sm text-g600">{PREVIEW_ERROR}</p>
          ) : (
            <>
              <p className="text-[13px] text-g600">
                Subject: <span className="font-medium text-foreground">{state.preview.subject}</span>
              </p>
              <pre
                data-testid="message-preview-text"
                className="max-h-48 overflow-auto rounded-md border border-edge bg-muted-fill p-3 font-mono text-[12px] leading-[18px] whitespace-pre-wrap text-g700"
              >
                {state.preview.text}
              </pre>
            </>
          )}
          {error ? (
            <p role="alert" className="text-[12.5px] text-red-600 dark:text-red-400">
              {error}
            </p>
          ) : null}
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
            onClick={() => void send()}
            disabled={!complete || sending}
            className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            {sending ? "…" : "Send"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
