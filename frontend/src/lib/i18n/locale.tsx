"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { DEFAULT_LOCALE, isLocale, translate, type Locale, type MessageKey } from "./messages";

/** Admin UI locale, kept per browser. Storage can be missing or throw
 * (private mode, blocked site data), so every access is guarded and the
 * app falls back to English. */
export const LOCALE_STORAGE_KEY = "ganek.admin.locale";

export function readStoredLocale(): Locale {
  try {
    const value = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return isLocale(value) ? value : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

function storeLocale(locale: Locale) {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    /* the choice still applies for this page view */
  }
}

type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
};

// Outside a provider (candidate pages, isolated component tests) the UI is English.
const LocaleContext = createContext<LocaleContextValue>({
  locale: DEFAULT_LOCALE,
  setLocale: storeLocale,
  t: (key, vars) => translate(DEFAULT_LOCALE, key, vars),
});

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() =>
    typeof window === "undefined" ? DEFAULT_LOCALE : readStoredLocale(),
  );

  useEffect(() => {
    // screen readers and hyphenation follow the admin language; restored on leaving the admin
    const root = document.documentElement;
    const previous = root.lang;
    root.lang = locale;
    return () => {
      root.lang = previous;
    };
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    storeLocale(next);
    setLocaleState(next);
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({ locale, setLocale, t: (key, vars) => translate(locale, key, vars) }),
    [locale, setLocale],
  );
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}
