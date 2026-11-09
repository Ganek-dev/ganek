import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { LOCALE_STORAGE_KEY, LocaleProvider } from "@/lib/i18n/locale";

import { LanguageCard } from "./LanguageCard";

describe("LanguageCard", () => {
  afterEach(() => window.localStorage.clear());

  it("switches the admin language and relabels itself", async () => {
    render(
      <LocaleProvider>
        <LanguageCard />
      </LocaleProvider>,
    );
    const select = screen.getByRole("combobox", { name: "Interface language" });
    expect(select).toHaveValue("en");
    expect(screen.queryByText(/German covers/)).not.toBeInTheDocument();

    await userEvent.selectOptions(select, "de");

    expect(screen.getByRole("combobox", { name: "Sprache der Oberfläche" })).toHaveValue("de");
    expect(screen.getByText("Sprache")).toBeInTheDocument();
    expect(screen.getByText(/bisher die Navigation/)).toBeInTheDocument();
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("de");
  });

  it("names each language in itself", () => {
    render(<LanguageCard />);
    expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Deutsch" })).toHaveAttribute("lang", "de");
  });
});
