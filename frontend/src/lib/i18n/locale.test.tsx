import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LOCALE_STORAGE_KEY, LocaleProvider, readStoredLocale, useLocale } from "./locale";

function Probe() {
  const { locale, setLocale, t } = useLocale();
  return (
    <button type="button" onClick={() => setLocale(locale === "en" ? "de" : "en")}>
      {t("shell.signOut")}
    </button>
  );
}

describe("LocaleProvider", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    document.documentElement.lang = "";
  });

  it("defaults to English and switches, storing the choice and the html lang", async () => {
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByRole("button", { name: "Abmelden" })).toBeInTheDocument();
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("de");
    expect(document.documentElement.lang).toBe("de");
  });

  it("starts from a stored locale and ignores an unknown one", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "de");
    expect(readStoredLocale()).toBe("de");
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "xx");
    expect(readStoredLocale()).toBe("en");
  });

  it("falls back to English when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readStoredLocale()).toBe("en");
  });

  it("renders English outside a provider", () => {
    render(<Probe />);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
