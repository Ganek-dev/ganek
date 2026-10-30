"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { ApiError, emailTemplates, type EmailKind, type EmailPreview } from "@/lib/api";
import { placeholderHelp } from "@/lib/email-placeholders";

/** The template editor (card "Candidate emails", PR 3): name, subject, a
 * plain-paragraph body, placeholder chips that insert at the cursor, and a
 * live sample preview rendered by the server (debounced), so the text the
 * admin reads is what the renderer produces. Save stays disabled while the
 * server reports an unknown placeholder or a field is blank. The parent
 * re-keys the editor per opening so it mounts with `initial`. */

export const EXPLAINER = "The link and the privacy footer are always added by Ganek.";
const DEBOUNCE_MS = 400;

type PreviewResult =
  | { kind: "ready"; preview: EmailPreview }
  | { kind: "invalid"; message: string }
  | { kind: "error" };

type PreviewState = PreviewResult | { kind: "idle" } | { kind: "loading" };

/** The server's answer for one exact subject + body; anything else on
 * screen is stale and renders as loading while the debounce runs. */
type Fetched = { subject: string; body: string; result: PreviewResult };

type Field = "subject" | "body";

const inputCls =
  "mt-1 block h-9 w-full rounded-md border border-edge bg-transparent px-3 text-[13.5px] outline-none focus:border-g400";

export function EmailTemplateEditor({
  open,
  kind,
  label,
  placeholders,
  initial,
  onSaved,
  onCancel,
}: {
  open: boolean;
  kind: EmailKind;
  label: string;
  placeholders: string[];
  initial: { id?: string; name: string; subject: string; body: string };
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial.name);
  const [subject, setSubject] = useState(initial.subject);
  const [body, setBody] = useState(initial.body);
  const [fetched, setFetched] = useState<Fetched | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const subjectRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const lastFocused = useRef<Field>("body");
  // where the caret goes after a chip insert, applied once the value rendered
  const pendingCaret = useRef<{ field: Field; at: number } | null>(null);

  useLayoutEffect(() => {
    const caret = pendingCaret.current;
    if (caret === null) return;
    pendingCaret.current = null;
    const element = caret.field === "subject" ? subjectRef.current : bodyRef.current;
    element?.focus();
    element?.setSelectionRange(caret.at, caret.at);
  }, [subject, body]);

  const textBlank = !subject.trim() || !body.trim();

  useEffect(() => {
    if (!open || textBlank) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      emailTemplates
        .preview({ kind, subject, body })
        .then((rendered) => {
          if (!cancelled) setFetched({ subject, body, result: { kind: "ready", preview: rendered } });
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          const result: PreviewResult =
            err instanceof ApiError && err.status === 422
              ? { kind: "invalid", message: err.detail }
              : { kind: "error" };
          setFetched({ subject, body, result });
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, kind, subject, body, textBlank]);

  const preview: PreviewState = textBlank
    ? { kind: "idle" }
    : fetched !== null && fetched.subject === subject && fetched.body === body
      ? fetched.result
      : { kind: "loading" };

  const blank = !name.trim() || textBlank;
  const canSave = !blank && preview.kind !== "invalid" && preview.kind !== "loading" && !saving;

  function insert(placeholder: string) {
    const token = `{{${placeholder}}}`;
    const field = lastFocused.current;
    const element = field === "subject" ? subjectRef.current : bodyRef.current;
    const value = field === "subject" ? subject : body;
    const start = element?.selectionStart ?? value.length;
    const end = element?.selectionEnd ?? value.length;
    const next = value.slice(0, start) + token + value.slice(end);
    const caret = start + token.length;
    if (field === "subject") setSubject(next);
    else setBody(next);
    // keep the caret after the token so a second chip lands next to it
    pendingCaret.current = { field, at: caret };
  }

  async function save() {
    setSaving(true);
    setSaveError(null);
    const payload = { name: name.trim(), subject: subject.trim(), body: body.trim() };
    try {
      if (initial.id) await emailTemplates.update(initial.id, payload);
      else await emailTemplates.create({ kind, ...payload });
      onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogTitle>{initial.id ? `Edit ${initial.name}` : `New ${label} template`}</DialogTitle>
        <DialogDescription>{EXPLAINER}</DialogDescription>
        <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <label className="block text-[13px] font-medium text-g700">
              Name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={80}
                className={inputCls}
              />
            </label>
            <label className="block text-[13px] font-medium text-g700">
              Subject
              <input
                ref={subjectRef}
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                onFocus={() => {
                  lastFocused.current = "subject";
                }}
                maxLength={200}
                className={inputCls}
              />
            </label>
            <label className="block text-[13px] font-medium text-g700">
              Body
              <textarea
                ref={bodyRef}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                onFocus={() => {
                  lastFocused.current = "body";
                }}
                rows={8}
                className="mt-1 block w-full rounded-md border border-edge bg-transparent px-3 py-2 font-mono text-[12.5px] leading-[18px] outline-none focus:border-g400"
              />
            </label>
            <div className="flex flex-wrap gap-1.5" aria-label="Placeholders">
              {placeholders.map((placeholder) => {
                const help = placeholderHelp(placeholder);
                return (
                  <button
                    key={placeholder}
                    type="button"
                    title={help.example ? `${help.label}: ${help.example}` : help.label}
                    onClick={() => insert(placeholder)}
                    className="inline-flex h-6 items-center rounded-sm border border-edge bg-muted-fill px-1.5 font-mono text-[11px] text-g700 hover:border-g400"
                  >
                    {`{{${placeholder}}}`}
                  </button>
                );
              })}
            </div>
            <p className="text-[11.5px] text-g500">
              The first paragraph is the heading of the email. Paragraphs are separated by a blank line.
            </p>
          </div>
          <div>
            <p className="text-[13px] font-medium text-g700">Preview</p>
            {preview.kind === "invalid" ? (
              <p role="alert" className="mt-1 text-[12.5px] text-red-600 dark:text-red-400">
                {preview.message}
              </p>
            ) : null}
            {preview.kind === "error" ? (
              <p className="mt-1 text-[12.5px] text-g600">Preview unavailable.</p>
            ) : null}
            {preview.kind === "loading" ? (
              <div aria-busy="true" aria-label="Loading preview" className="mt-1 space-y-2">
                <div className="h-5 w-48 animate-pulse rounded-sm bg-muted-fill" />
                <div className="h-40 animate-pulse rounded-md bg-muted-fill" />
              </div>
            ) : null}
            {preview.kind === "ready" ? (
              <>
                <p className="mt-1 text-[13px] text-g600">
                  Subject:{" "}
                  <span className="font-medium text-foreground">{preview.preview.subject}</span>
                </p>
                <pre
                  data-testid="template-preview-text"
                  className="mt-2 max-h-72 overflow-auto rounded-md border border-edge bg-muted-fill p-3 font-mono text-[12px] leading-[18px] whitespace-pre-wrap text-g700"
                >
                  {preview.preview.text}
                </pre>
              </>
            ) : null}
            {preview.kind === "idle" ? (
              <p className="mt-1 text-[12.5px] text-g500">
                Type a subject and a body to see the sample email.
              </p>
            ) : null}
          </div>
        </div>
        {saveError ? (
          <p role="alert" className="mt-3 text-[12.5px] text-red-600 dark:text-red-400">
            {saveError}
          </p>
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
            onClick={() => void save()}
            disabled={!canSave}
            className="inline-flex h-8 items-center rounded-md bg-accent px-3.5 text-[13px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
