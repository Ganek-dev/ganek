"use client";

import { useEffect, useRef, useState } from "react";

import { X } from "lucide-react";

/** One transient confirmation with an optional action (board card
 * "Candidate timeline": "Moved Erika to Screening. Undo"). The live region
 * is always mounted so screen readers announce the text when it changes;
 * the timer pauses while the pointer or focus is on the toast so the
 * action stays reachable. Never the only way back: the panel keeps its
 * stage controls. */

export interface ToastMessage {
  id: number;
  text: string;
  action?: { label: string; run: () => void | Promise<void> };
}

export const TOAST_MS = 8000;

export function Toast({
  message,
  onDismiss,
}: {
  message: ToastMessage | null;
  onDismiss: () => void;
}) {
  const [held, setHeld] = useState(false);
  const [busy, setBusy] = useState(false);
  // latest onDismiss without restarting the timer on every parent render
  const dismiss = useRef(onDismiss);
  useEffect(() => {
    dismiss.current = onDismiss;
  });

  useEffect(() => {
    if (message === null || held) return;
    const id = setTimeout(() => dismiss.current(), TOAST_MS);
    return () => clearTimeout(id);
  }, [message, held]);

  async function act() {
    if (!message?.action) return;
    setBusy(true);
    try {
      await message.action.run();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-6 z-40 flex justify-center px-4"
    >
      {message !== null ? (
        <div
          key={message.id}
          onMouseEnter={() => setHeld(true)}
          onMouseLeave={() => setHeld(false)}
          onFocus={() => setHeld(true)}
          onBlur={() => setHeld(false)}
          className="pointer-events-auto flex max-w-full items-center gap-3 rounded-md border border-edge bg-surface px-3.5 py-2.5 text-[13px] text-g700 shadow-lg"
        >
          <span>{message.text}</span>
          {message.action ? (
            <button
              type="button"
              onClick={act}
              disabled={busy}
              className="font-semibold text-accent underline-offset-2 hover:underline disabled:opacity-50"
            >
              {message.action.label}
            </button>
          ) : null}
          <button
            type="button"
            aria-label="Dismiss"
            onClick={onDismiss}
            className="-mr-1 inline-flex h-6 w-6 items-center justify-center rounded-sm text-g500 hover:bg-muted-fill/60"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
