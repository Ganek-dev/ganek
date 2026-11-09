"use client";

import { useEffect, useMemo, useState } from "react";

import { Clock } from "lucide-react";

import { api, type Availability, type DayKey, type DayWindow } from "@/lib/api";
import { useLocale } from "@/lib/i18n/locale";

/** Account settings card: the recruiter's weekly interview-availability
 * window, used by the slot engine to offer times to candidates, plus the
 * default meeting location copied onto each interview request. Loads the
 * saved (or default Mon-Fri 9-17) schedule, edits happen client-side, Save
 * PUTs the whole week + the browser's IANA zone + the location. */

const DAYS: DayKey[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

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
  const { t } = useLocale();
  const [loaded, setLoaded] = useState(false);
  const [days, setDays] = useState<Partial<Record<DayKey, DayWindow>>>({});
  const [location, setLocation] = useState("");
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
        setLocation(res.location ?? "");
        setIsDefault(res.is_default);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : t("availability.loadFailed"));
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
    // load once; a language switch must not refetch and drop unsaved edits
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const invalidDay = DAYS.find((d) => {
    const window = days[d];
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
      const result = await api.availability.set({
        timezone: browserZone,
        days,
        location: location.trim(),
      });
      setDays(result.days);
      setLocation(result.location ?? "");
      setIsDefault(result.is_default);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("availability.saveFailed"));
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
            {t("availability.title")}
          </p>
          <p className="mt-0.5 text-[12.5px] text-g500">{t("availability.description")}</p>
        </div>
        <span className="inline-flex h-6 shrink-0 items-center rounded-full border border-edge px-2.5 text-[11px] font-medium text-g500">
          <span className="font-mono text-g600">{browserZone}</span>
          &nbsp;{t("availability.yourZone")}
        </span>
      </div>

      {isDefault ? (
        <p className="mt-3 rounded-md border border-edge bg-muted-fill/40 px-3 py-2 text-[12.5px] text-g500">
          {t("availability.defaultHours")}
        </p>
      ) : null}

      <div className="mt-4 flex flex-col">
        {DAYS.map((key) => {
          const window = days[key];
          const enabled = Boolean(window);
          const label = t(`day.${key}`);
          return (
            <div
              key={key}
              className="flex items-center gap-3 border-b border-edge py-2 last:border-b-0"
            >
              <label className="flex w-20 shrink-0 items-center gap-2">
                <input
                  type="checkbox"
                  aria-label={label}
                  checked={enabled}
                  onChange={() => toggleDay(key)}
                  className="h-4 w-4 rounded border-edge"
                />
                <span className="text-[13px] font-medium">{t(`dayShort.${key}`)}</span>
              </label>
              <select
                aria-label={t("availability.startTime", { day: label })}
                value={window?.start ?? DEFAULT_WINDOW.start}
                disabled={!enabled}
                onChange={(event) => setTime(key, "start", event.target.value)}
                className={selectCls}
              >
                {TIME_OPTIONS.map((time) => (
                  <option key={time} value={time}>
                    {time}
                  </option>
                ))}
              </select>
              <span aria-hidden className="text-g500">
                -
              </span>
              <select
                aria-label={t("availability.endTime", { day: label })}
                value={window?.end ?? DEFAULT_WINDOW.end}
                disabled={!enabled}
                onChange={(event) => setTime(key, "end", event.target.value)}
                className={selectCls}
              >
                {TIME_OPTIONS.map((time) => (
                  <option key={time} value={time}>
                    {time}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>

      <label className="mt-4 flex flex-col gap-1.5">
        <span className="text-[13px] font-medium">{t("availability.location")}</span>
        <input
          type="text"
          value={location}
          maxLength={500}
          onChange={(event) => {
            setSaved(false);
            setLocation(event.target.value);
          }}
          placeholder={t("availability.locationPlaceholder")}
          className="h-9 rounded-md border border-edge bg-transparent px-2.5 text-[13px] outline-none focus:border-g400"
        />
      </label>
      <p className="mt-1.5 text-[12px] text-g500">
        {t("availability.locationHint")}
      </p>

      <div className="mt-4">
        {invalidDay ? (
          <p className="mb-2 text-sm text-red-600 dark:text-red-400">
            {t("availability.invalid", { day: t(`day.${invalidDay}`) })}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="mb-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
        {saved ? (
          <p className="mb-2 text-sm text-emerald-700 dark:text-emerald-400">{t("availability.saved")}</p>
        ) : null}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || Boolean(invalidDay)}
          className="inline-flex h-8 items-center rounded-md bg-inverse px-3.5 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          {saving ? "…" : t("availability.save")}
        </button>
      </div>
    </div>
  );
}
