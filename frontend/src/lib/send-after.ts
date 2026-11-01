/** "Send later" presets for the rejection email (delayed rejection card).
 * The server stores an instant, so the preset is sent with the browser's
 * UTC offset: 09:00 local stays 09:00 local, not the UTC reading of it. */
export type SendAfterPreset = "now" | "tomorrow" | "in_3_days";

export const PRESET_LABELS: Record<SendAfterPreset, string> = {
  now: "Send now",
  tomorrow: "Tomorrow morning",
  in_3_days: "In 3 days",
};

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const PRESET_DAYS: Record<Exclude<SendAfterPreset, "now">, number> = {
  tomorrow: 1,
  in_3_days: 3,
};

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** YYYY-MM-DDTHH:mm:ss+HH:MM in the date's own local zone (toISOString would
 * convert to UTC). */
function toLocalIso(d: Date): string {
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
  );
}

/** The send_after value for a preset: null means now, otherwise 09:00 local
 * on the next calendar day or three days on. */
export function presetSendAfter(preset: SendAfterPreset, now: Date = new Date()): string | null {
  if (preset === "now") return null;
  const target = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate() + PRESET_DAYS[preset],
    9,
    0,
    0,
  );
  return toLocalIso(target);
}

/** "Mon 09:00" within the next 6 calendar days, "Tue 4 Nov 09:00" after,
 * in the browser zone on a 24 h clock. */
export function formatSendAfter(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const startOf = (x: Date) => Date.UTC(x.getFullYear(), x.getMonth(), x.getDate());
  const diffDays = Math.round((startOf(d) - startOf(now)) / 86_400_000);
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const weekday = DAYS[d.getDay()];
  if (diffDays >= 0 && diffDays <= 6) return `${weekday} ${time}`;
  return `${weekday} ${d.getDate()} ${MONTHS[d.getMonth()]} ${time}`;
}
