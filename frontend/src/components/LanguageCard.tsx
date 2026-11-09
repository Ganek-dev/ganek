"use client";

import { useLocale } from "@/lib/i18n/locale";
import { LOCALE_NAMES, LOCALES, isLocale } from "@/lib/i18n/messages";

/** Account page: the admin UI language for this browser. */
export function LanguageCard() {
  const { locale, setLocale, t } = useLocale();
  return (
    <div className="card p-5">
      <p className="text-sm font-semibold">{t("language.title")}</p>
      <p className="mt-0.5 text-[12.5px] text-g500">{t("language.description")}</p>
      <label className="mt-4 flex max-w-[260px] flex-col gap-1.5">
        <span className="text-[13px] font-medium">{t("language.label")}</span>
        <select
          value={locale}
          onChange={(event) => {
            if (isLocale(event.target.value)) setLocale(event.target.value);
          }}
          className="h-9 w-full rounded-md border border-edge bg-transparent px-2.5 text-sm outline-none focus:border-g400"
        >
          {LOCALES.map((code) => (
            <option key={code} value={code} lang={code}>
              {LOCALE_NAMES[code]}
            </option>
          ))}
        </select>
      </label>
      {locale !== "en" ? (
        <p className="mt-3 text-[12.5px] text-g500">{t("language.partial")}</p>
      ) : null}
    </div>
  );
}
