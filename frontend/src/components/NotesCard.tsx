"use client";

import { useEffect, useState } from "react";

import { X } from "lucide-react";

import { api, notes, type Note, type UserOut } from "@/lib/api";

/** Internal recruiter notes on an applicant (screen 11 detail panel, below
 * the Integrity card). Self-contained: fetches its own note list + the
 * current user (for delete visibility) once per applicant. Notes are
 * always company-authored — every row gets the same "internal" blue tint. */

function relativeTime(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function authorLabel(email: string | null): string {
  return email ? email.split("@")[0] : "former teammate";
}

function NoteRow({
  note: item,
  canDelete,
  onDeleted,
}: {
  note: Note;
  canDelete: boolean;
  onDeleted: (id: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirmDelete() {
    setError(null);
    setBusy(true);
    try {
      await onDeleted(item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete note");
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <li className="rounded-md px-3 py-2 [background-color:oklch(0.95_0.038_250)] dark:[background-color:oklch(0.28_0.05_250)]">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] leading-[19px] text-[oklch(0.40_0.090_250)] dark:text-[oklch(0.88_0.04_250)]">
          {item.body}
        </p>
        {canDelete && !confirming ? (
          <button
            type="button"
            aria-label="Delete note"
            onClick={() => setConfirming(true)}
            className="shrink-0 text-[oklch(0.40_0.090_250)]/60 hover:text-red-600 dark:text-[oklch(0.88_0.04_250)]/60 dark:hover:text-red-400"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      <div className="mt-1 flex items-center justify-between gap-3">
        <p className="text-[11.5px] text-g500">
          {authorLabel(item.author_email)} · {relativeTime(item.created_at)}
        </p>
        {confirming ? (
          <p className="flex items-center gap-1.5 text-[11.5px]">
            Delete?
            <button
              type="button"
              disabled={busy}
              onClick={confirmDelete}
              className="font-semibold text-red-600 hover:underline disabled:opacity-50 dark:text-red-400"
            >
              Yes
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirming(false)}
              className="text-g500 hover:underline disabled:opacity-50"
            >
              No
            </button>
          </p>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-[11.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function NotesCard({ applicationId }: { applicationId: string }) {
  const [items, setItems] = useState<Note[]>([]);
  const [me, setMe] = useState<UserOut | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([notes.list(applicationId), api.me()])
      .then(([list, user]) => {
        if (cancelled) return;
        setItems(list);
        setMe(user);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load notes");
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  async function addNote() {
    const body = draft.trim();
    if (!body || busy) return;
    setError(null);
    setBusy(true);
    try {
      const created = await notes.add(applicationId, body);
      setItems((prev) => [...prev, created]);
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setBusy(false);
    }
  }

  async function removeNote(noteId: string) {
    await notes.remove(applicationId, noteId);
    setItems((prev) => prev.filter((n) => n.id !== noteId));
  }

  if (!loaded) {
    return (
      <div className="card mt-5 p-4">
        <div aria-busy="true" className="h-16 animate-pulse rounded-md bg-muted-fill" />
      </div>
    );
  }

  return (
    <div className="card mt-5 p-4">
      <div className="flex items-center gap-2">
        <p className="text-[13px] font-semibold">Notes</p>
        <span className="inline-flex h-5 items-center rounded-full border border-edge bg-muted-fill px-2 font-mono text-[11px] font-medium text-g600">
          {items.length}
        </span>
      </div>

      {items.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <NoteRow
              key={item.id}
              note={item}
              canDelete={me !== null && (me.role === "admin" || item.author_email === me.email)}
              onDeleted={removeNote}
            />
          ))}
        </ul>
      ) : null}

      <div className="mt-3 flex items-center gap-2">
        <input
          type="text"
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void addNote();
            }
          }}
          placeholder="Add a note for the team…"
          className="h-8 flex-1 rounded-md border border-edge bg-surface px-2.5 text-[13px] outline-none focus:border-accent disabled:opacity-60"
        />
        <button
          type="button"
          disabled={busy || draft.trim() === ""}
          onClick={() => void addNote()}
          className="inline-flex h-8 shrink-0 items-center rounded-md bg-inverse px-3 text-[12.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : "Add"}
        </button>
      </div>

      {error ? (
        <p role="alert" className="mt-2 text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}
