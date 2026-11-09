/** Compact relative age for admin surfaces ("just now", "5m ago", "3h ago",
 * "2d ago", "3w ago"). Was copy-pasted into four components before M5.7 H5. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const { unit, n } = relativeAge(iso, now);
  if (unit === "now") return "just now";
  return `${n}${unit} ago`;
}

export type RelativeAge = { unit: "now" | "m" | "h" | "d" | "w"; n: number };

/** The unit and count behind `relativeTime`, for callers that word it in
 * another language (`formatAge` in lib/i18n/locale). */
export function relativeAge(iso: string, now: Date = new Date()): RelativeAge {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return { unit: "now", n: 0 };
  if (seconds < 3600) return { unit: "m", n: Math.round(seconds / 60) };
  if (seconds < 86400) return { unit: "h", n: Math.round(seconds / 3600) };
  const days = Math.round(seconds / 86400);
  if (days < 7) return { unit: "d", n: days };
  return { unit: "w", n: Math.round(days / 7) };
}

/** "31 Oct 2026". Local time of the viewer. */
export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** "3 Nov 2026, 10:00", in `timeZone` when given (and valid), else the
 * viewer's local time. */
export function formatDateTime(iso: string, timeZone?: string): string {
  const opts: Intl.DateTimeFormatOptions = {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  };
  const date = new Date(iso);
  try {
    return date.toLocaleString("en-GB", { ...opts, timeZone });
  } catch {
    return date.toLocaleString("en-GB", opts);
  }
}

/** "18:13", local time of the viewer; "" for a missing or unparseable value. */
export function shortTime(value: unknown): string {
  if (typeof value !== "string") return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
