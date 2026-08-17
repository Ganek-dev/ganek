"use client";

import { useRef, useState } from "react";

import { Check, Copy } from "lucide-react";

/** Small copy-to-clipboard button with a 1.5s "copied" confirmation. The
 * clipboard call failing is silent by default — every call site keeps the
 * text visible and selectable right next to the button. */
export function CopyButton({
  text,
  label,
  children,
  className = "",
  onError,
}: {
  text: string;
  label: string;
  children?: React.ReactNode;
  className?: string;
  onError?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      onError?.();
    }
  }

  return (
    <button
      type="button"
      aria-label={label}
      onClick={copy}
      className={
        className ||
        "inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-edge bg-surface px-2 text-[12px] font-medium text-g700 hover:bg-muted-fill"
      }
    >
      {copied ? (
        <>
          <Check aria-hidden className="h-3 w-3 text-ok" />
          Copied
        </>
      ) : (
        <>
          <Copy aria-hidden className="h-3 w-3" />
          {children ?? "Copy"}
        </>
      )}
    </button>
  );
}
