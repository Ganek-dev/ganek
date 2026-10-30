"use client";

import { useCallback, useEffect, useState } from "react";

import { EmailTemplateEditor } from "@/components/EmailTemplateEditor";
import { SettingsTabs } from "@/components/SettingsTabs";
import { emailTemplates, type EmailKindInfo, type EmailTemplate } from "@/lib/api";

/** Emails settings (card "Candidate emails", PR 3): the workspace's own
 * templates per stage mail kind. "Ganek default" is the built-in text and
 * stays available; a custom template can be the kind's default. The
 * editor itself lands with the next task; this page lists, switches the
 * default and deletes. Admin-only like Privacy. */

export const EXPLAINER = "The link and the privacy footer are always added by Ganek.";

export type EditorTarget =
  | { kind: EmailKindInfo; template: EmailTemplate | null; duplicateOf: EmailTemplate | null }
  | null;

const btn =
  "inline-flex h-7 items-center rounded-sm border border-edge bg-surface px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50";

export default function EmailsSettingsPage() {
  const [kinds, setKinds] = useState<EmailKindInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  // the editor opens from New template, Duplicate and Edit; re-keyed per
  // opening so it mounts with the prefilled text
  const [editing, setEditing] = useState<EditorTarget>(null);
  const [editorKey, setEditorKey] = useState(0);

  function openEditor(target: EditorTarget) {
    setEditorKey((key) => key + 1);
    setEditing(target);
  }

  const load = useCallback(() => {
    return emailTemplates
      .list()
      .then((data) => setKinds(data.kinds))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load templates"),
      );
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      setFlash(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The change failed");
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  }

  return (
    <section className="max-w-[880px] space-y-4">
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Emails</h1>
      <SettingsTabs />
      <p className="text-[12.5px] leading-[18px] text-g500">{EXPLAINER}</p>
      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
      {flash ? (
        <p role="status" className="text-[12.5px] text-emerald-700 dark:text-emerald-400">
          {flash}
        </p>
      ) : null}
      {kinds === null ? (
        !error ? (
          <div aria-busy="true" aria-label="Loading templates" className="space-y-2">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-lg bg-muted-fill" />
            ))}
          </div>
        ) : null
      ) : (
        kinds.map((kind) => {
          const hasCustomDefault = kind.templates.some((t) => t.is_default);
          const headingId = `emails-${kind.kind}`;
          return (
            <section key={kind.kind} aria-labelledby={headingId} className="card p-4">
              <div className="flex items-center justify-between">
                <h2 id={headingId} className="text-[13.5px] font-semibold">
                  {kind.label}
                </h2>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => openEditor({ kind, template: null, duplicateOf: null })}
                  className={btn}
                >
                  New template
                </button>
              </div>
              <ul className="mt-2 divide-y divide-divider">
                <li className="flex flex-wrap items-center gap-2 py-2">
                  <span data-testid="template-name" className="text-[13px] font-medium">
                    Ganek default
                  </span>
                  {!hasCustomDefault ? <DefaultBadge /> : null}
                  <span className="ml-auto flex gap-1.5">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        openEditor({
                          kind,
                          template: null,
                          duplicateOf: {
                            id: "builtin",
                            kind: kind.kind,
                            name: "Ganek default",
                            subject: kind.builtin.subject,
                            body: kind.builtin.body,
                            is_default: !hasCustomDefault,
                            created_at: "",
                            updated_at: "",
                          },
                        })
                      }
                      className={btn}
                    >
                      Duplicate
                    </button>
                  </span>
                </li>
                {kind.templates.map((template) => (
                  <li key={template.id} className="flex flex-wrap items-center gap-2 py-2">
                    <span data-testid="template-name" className="text-[13px] font-medium">
                      {template.name}
                    </span>
                    {template.is_default ? <DefaultBadge /> : null}
                    <span className="ml-auto flex flex-wrap gap-1.5">
                      {confirming === template.id ? (
                        <>
                          <span className="self-center text-[12.5px] text-g600">
                            Delete {template.name}?
                          </span>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                              void run(() => emailTemplates.remove(template.id), "Template deleted")
                            }
                            className="inline-flex h-7 items-center rounded-sm bg-red-600 px-2.5 text-[12.5px] font-medium text-white hover:brightness-[0.94] disabled:opacity-50"
                          >
                            Yes, delete
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setConfirming(null)}
                            className={btn}
                          >
                            Keep
                          </button>
                        </>
                      ) : (
                        <>
                          {!template.is_default ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                void run(
                                  () => emailTemplates.setDefault(template.id),
                                  "Default updated",
                                )
                              }
                              className={btn}
                            >
                              Set as default
                            </button>
                          ) : null}
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => openEditor({ kind, template: null, duplicateOf: template })}
                            className={btn}
                          >
                            Duplicate
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => openEditor({ kind, template, duplicateOf: null })}
                            className={btn}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setConfirming(template.id)}
                            className={btn}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })
      )}
      {editing ? (
        <EmailTemplateEditor
          key={editorKey}
          open
          kind={editing.kind.kind}
          label={editing.kind.label}
          placeholders={editing.kind.placeholders}
          initial={
            editing.template
              ? {
                  id: editing.template.id,
                  name: editing.template.name,
                  subject: editing.template.subject,
                  body: editing.template.body,
                }
              : editing.duplicateOf
                ? {
                    name: `${editing.duplicateOf.name} (copy)`,
                    subject: editing.duplicateOf.subject,
                    body: editing.duplicateOf.body,
                  }
                : { name: "", subject: "", body: "" }
          }
          onSaved={() => {
            setEditing(null);
            void load().then(() => setFlash("Template saved"));
          }}
          onCancel={() => setEditing(null)}
        />
      ) : null}
    </section>
  );
}

function DefaultBadge() {
  return (
    <span className="inline-flex h-5 items-center rounded-sm bg-muted-fill px-1.5 text-[11px] font-medium text-g600">
      Default
    </span>
  );
}
