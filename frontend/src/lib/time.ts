/** Compact relative age for admin surfaces ("just now", "5m ago", "3h ago",
 * "2d ago", "3w ago"). Was copy-pasted into four components before M5.7 H5. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  const days = Math.round(seconds / 86400);
  if (days < 7) return `${days}d ago`;
  return `${Math.round(days / 7)}w ago`;
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
