import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiKeys, type ApiKey } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale";

import { ApiKeysCard } from "./ApiKeysCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    apiKeys: { ...original.apiKeys, list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
  };
});

const mocked = vi.mocked(apiKeys);

describe("ApiKeysCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("tells admins that read keys also fetch CVs", async () => {
    mocked.list.mockResolvedValue([]);
    render(<ApiKeysCard />);
    await vi.waitFor(() => expect(mocked.list).toHaveBeenCalled());
    expect(screen.getByTestId("api-keys-card")).toHaveTextContent(
      "lists applicants, exports and fetches CVs",
    );
  });
});

describe("ApiKeysCard in German", () => {
  const keys: ApiKey[] = [
    {
      id: "k1",
      name: "Zapier",
      prefix: "gk_live_ab12",
      scope: "read",
      created_at: "2026-10-01T10:00:00Z",
      last_used_at: null,
      revoked_at: null,
    },
    {
      id: "k2",
      name: "Old script",
      prefix: "gk_live_cd34",
      scope: "write",
      created_at: "2026-09-01T10:00:00Z",
      last_used_at: "2026-09-10T10:00:00Z",
      revoked_at: "2026-10-05T10:00:00Z",
    },
  ];

  const renderGerman = () =>
    render(
      <LocaleProvider>
        <ApiKeysCard />
      </LocaleProvider>,
    );

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.setItem("ganek.admin.locale", "de");
  });
  afterEach(() => window.localStorage.clear());

  it("renders the form, the list and German dates", async () => {
    mocked.list.mockResolvedValue(keys);
    renderGerman();
    const card = screen.getByTestId("api-keys-card");
    expect(within(card).getByText("API-Schlüssel")).toBeInTheDocument();
    expect(card).toHaveTextContent("read listet Bewerbungen auf");
    expect(within(card).getByText("write", { selector: "p > span" })).toHaveClass("font-mono");
    expect(screen.getByLabelText("Name des Schlüssels")).toBeInTheDocument();
    expect(screen.getByLabelText("Berechtigung")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schlüssel erstellen" })).toBeInTheDocument();
    expect(await screen.findByText("zuletzt verwendet: nie")).toBeInTheDocument();
    expect(screen.getByText("widerrufen am 5. Okt.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Zapier widerrufen" }));
    expect(screen.getByRole("button", { name: "Schlüssel widerrufen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Behalten" })).toBeInTheDocument();
  });

  it("shows the German empty state and the one-time secret", async () => {
    mocked.list.mockResolvedValue([]);
    mocked.create.mockResolvedValue({ ...keys[0], secret: "gk_live_SECRET" });
    renderGerman();
    expect(await screen.findByText("Noch keine Schlüssel.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name des Schlüssels"), "Zapier");
    await userEvent.click(screen.getByRole("button", { name: "Schlüssel erstellen" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Zapier ist bereit. Kopieren Sie den Schlüssel jetzt",
    );
    expect(screen.getByRole("button", { name: "API-Schlüssel kopieren" })).toHaveTextContent(
      "Kopieren",
    );
  });
});
