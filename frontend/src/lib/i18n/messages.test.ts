import { describe, expect, it } from "vitest";

import { LOCALES, MESSAGES, translate, type MessageKey } from "./messages";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("admin message catalog", () => {
  const keys = Object.keys(MESSAGES.en) as MessageKey[];

  it.each(LOCALES)("%s has exactly the English keys, none empty", (locale) => {
    expect(Object.keys(MESSAGES[locale]).sort()).toEqual([...keys].sort());
    for (const key of keys) expect(MESSAGES[locale][key].trim(), `${locale}:${key}`).not.toBe("");
  });

  it.each(LOCALES)("%s keeps the English placeholders", (locale) => {
    for (const key of keys) {
      expect(placeholders(MESSAGES[locale][key]), `${locale}:${key}`).toEqual(
        placeholders(MESSAGES.en[key]),
      );
    }
  });

  it("fills placeholders and leaves unknown ones visible", () => {
    expect(translate("de", "nav.applicantsNew", { count: 7 })).toBe("7 neu");
    expect(translate("en", "nav.applicantsAria", { count: 2 })).toBe(
      "Applicants, 2 new applicants",
    );
    expect(translate("en", "nav.applicantsNew")).toBe("{count} new");
  });
});
