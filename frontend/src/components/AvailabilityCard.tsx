"use client";

import { useEffect, useMemo, useState } from "react";

import { Clock } from "lucide-react";

import { api, type Availability, type DayKey, type DayWindow } from "@/lib/api";

/** Account settings card: the recruiter's weekly interview-availability
 * window, used by the slot engine to offer times to candidates. Loads the
 * saved (or default Mon-Fri 9-17) schedule, edits happen client-side, Save
 * PUTs the whole week + the browser's IANA zone. */

const DAYS: { key: DayKey; label: string; short: string }[] = [
  { key: "mon", label: "Monday", short: "Mon" },
  { key: "tue", label: "Tuesday", short: "Tue" },
  { key: "wed", label: "Wednesday", short: "Wed" },
  { key: "thu", label: "Thursday", short: "Thu" },
  { key: "fri", label: "Friday", short: "Fri" },
  { key: "sat", label: "Saturday", short: "Sat" },
  { key: "sun", label: "Sunday", short: "Sun" },
];

const DEFAULT_WINDOW: DayWindow = { start: "09:00", end: "17:00" };

function buildTimeOptions(): string[] {
  const times: string[] = [];
  for (let hour = 0; hour < 24; hour++) {
    for (const minute of [0, 30]) {
      times.push(`${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`);
    }
  }
  return times;
}

const TIME_OPTIONS = buildTimeOptions();

const selectCls =
  "h-8 rounded-md border border-edge bg-transparent px-2 text-[13px] outline-none focus:border-g400 disabled:opacity-40";

export function AvailabilityCard() {
  const [loaded, setLoaded] = useState(false);
  const [days, setDays] = useState<Partial<Record<DayKey, DayWindow>>>({});
  const [isDefault, setIsDefault] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const browserZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  useEffect(() => {
    let cancelled = false;
    api
      .availability.get()
      .then((res: Availability) => {
        if (cancelled) return;
        setDays(res.days);
        setIsDefault(res.is_default);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load availability");
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const invalidDay = DAYS.find((d) => {
    const window = days[d.key];
    return window ? window.start >= window.end : false;
  });

  function toggleDay(key: DayKey) {
    setSaved(false);
    setDays((prev) => {
      if (prev[key]) {
        const next = { ...prev };
        delete next[key];
        return next;
      }
      return { ...prev, [key]: { ...DEFAULT_WINDOW } };
    });
  }

  function setTime(key: DayKey, field: "start" | "end", value: string) {
    setSaved(false);
    setDays((prev) => {
      const current = prev[key];
      if (!current) return prev;
      return { ...prev, [key]: { ...current, [field]: value } };
    });
  }

  async function handleSave() {
    setError(null);
    setSaved(false);
    setSaving(true);
    try {
      const result = await api.availability.set({ timezone: browserZone, days });
      setDays(result.days);
      setIsDefault(result.is_default);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save availability");
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) {
    return (
      <div className="card p-5">
        <div aria-busy="true" className="h-32 animate-pulse rounded-md bg-muted-fill" />
      </div>
    );
  }

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <Clock aria-hidden className="h-4 w-4 text-g500" />
            Interview availability
          </p>
          <p className="mt-0.5 text-[12.5px] text-g500">
            When candidates can book interview slots with you.
          </p>
        </div>
        <span className="inline-flex h-6 shrink-0 items-center rounded-full border border-edge px-2.5 text-[11px] font-medium text-g500">
          <span className="font-mono text-g600">{browserZone}</span>
          &nbsp;— your timezone
        </span>
      </div>

      {isDefault ? (
        <p className="mt-3 rounded-md border border-edge bg-muted-fill/40 px-3 py-2 text-[12.5px] text-g500">
          Using default hours — Mon–Fri 9:00–17:00.
        </p>
      ) : null}

      <div className="mt-4 flex flex-col">
        {DAYS.map((day) => {
          const window = days[day.key];
          const enabled = Boolean(window);
          return (
            <div
              key={day.key}
              className="flex items-center gap-3 border-b border-edge py-2 last:border-b-0"
            >
              <label className="flex w-20 shrink-0 items-center gap-2">
                <input
                  type="checkbox"
                  aria-label={day.label}
                  checked={enabled}
                  onChange={() => toggleDay(day.key)}
                  className="h-4 w-4 rounded border-edge"
                />
                <span className="text-[13px] font-medium">{day.short}</span>
              </label>
              <select
                aria-label={`${day.label} start time`}
                value={window?.start ?? DEFAULT_WINDOW.start}
                disabled={!enabled}
                onChange={(event) => setTime(day.key, "start", event.target.value)}
                className={selectCls}
              >
                {TIME_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <span aria-hidden className="text-g500">
                –
              </span>
              <select
                aria-label={`${day.label} end time`}
                value={window?.end ?? DEFAULT_WINDOW.end}
                disabled={!enabled}
                onChange={(event) => setTime(day.key, "end", event.target.value)}
                className={selectCls}
              >
                {TIME_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>

      <div className="mt-4">
        {invalidDay ? (
          <p className="mb-2 text-sm text-red-600 dark:text-red-400">
            {invalidDay.label}: start must be before end.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="mb-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
        {saved ? (
          <p className="mb-2 text-sm text-emerald-700 dark:text-emerald-400">Saved.</p>
        ) : null}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || Boolean(invalidDay)}
          className="inline-flex h-8 items-center rounded-md bg-inverse px-3.5 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {saving ? "…" : "Save availability"}
        </button>
      </div>
    </div>
  );
}
