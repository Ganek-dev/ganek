import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, companyApi, type CustomDomainOut } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale";

import { CustomDomainCard } from "./CustomDomainCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: {
      domain: vi.fn(),
      setDomain: vi.fn(),
      verifyDomain: vi.fn(),
      removeDomain: vi.fn(),
    },
  };
});

const mocked = vi.mocked(companyApi);

function make(overrides: Partial<CustomDomainOut> = {}): CustomDomainOut {
  return {
    available: true,
    upgrade_url: null,
    domain: null,
    status: "none",
    txt_name: null,
    txt_value: null,
    verified_at: null,
    ...overrides,
  };
}

const pending = make({
  domain: "careers.acme.com",
  status: "pending",
  txt_name: "_ganek.careers.acme.com",
  txt_value: "ganek-domain-verification=abc123",
});

describe("CustomDomainCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when the plan has no custom domains and nothing to upgrade to", async () => {
    mocked.domain.mockResolvedValue(make({ available: false }));
    const { container } = render(<CustomDomainCard />);
    await waitFor(() => expect(mocked.domain).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("offers the upgrade link when the plan lacks the feature", async () => {
    mocked.domain.mockResolvedValue(
      make({ available: false, upgrade_url: "https://ganek.io/pricing" }),
    );
    render(<CustomDomainCard />);
    expect(await screen.findByText(/part of the Team plan/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upgrade plan" })).toHaveAttribute(
      "href",
      "https://ganek.io/pricing",
    );
    expect(screen.queryByLabelText("Custom domain")).not.toBeInTheDocument();
  });

  it("adds a domain and shows the TXT record as pending DNS", async () => {
    mocked.domain.mockResolvedValue(make());
    mocked.setDomain.mockResolvedValue(pending);
    render(<CustomDomainCard />);
    await userEvent.type(await screen.findByLabelText("Custom domain"), " careers.acme.com ");
    await userEvent.click(screen.getByRole("button", { name: "Add domain" }));
    expect(mocked.setDomain).toHaveBeenCalledWith("careers.acme.com");
    expect(await screen.findByText("pending DNS")).toBeInTheDocument();
    expect(screen.getByText("_ganek.careers.acme.com")).toBeInTheDocument();
    expect(screen.getByText("ganek-domain-verification=abc123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy TXT name" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy TXT value" })).toBeInTheDocument();
  });

  it("surfaces the server's reason for an invalid domain", async () => {
    mocked.domain.mockResolvedValue(make());
    mocked.setDomain.mockRejectedValue(
      new ApiError(422, "Enter the domain only, without https:// or a path"),
    );
    render(<CustomDomainCard />);
    await userEvent.type(await screen.findByLabelText("Custom domain"), "https://x.com");
    await userEvent.click(screen.getByRole("button", { name: "Add domain" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("without https://");
  });

  it("verifies a pending domain", async () => {
    mocked.domain.mockResolvedValue(pending);
    mocked.verifyDomain.mockResolvedValue(
      make({ domain: "careers.acme.com", status: "verified", verified_at: "2026-11-08T10:00:00Z" }),
    );
    render(<CustomDomainCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Verify" }));
    expect(await screen.findByText("verified")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Domain verified");
    expect(screen.queryByText("_ganek.careers.acme.com")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify" })).not.toBeInTheDocument();
  });

  it("keeps the record visible and explains when the TXT record is not found yet", async () => {
    mocked.domain.mockResolvedValue(pending);
    mocked.verifyDomain.mockRejectedValue(
      new ApiError(409, "No TXT record _ganek.careers.acme.com with the value x was found yet."),
    );
    render(<CustomDomainCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("was found yet");
    expect(screen.getByText("pending DNS")).toBeInTheDocument();
    expect(screen.getByText("_ganek.careers.acme.com")).toBeInTheDocument();
  });

  it("removes a domain kept after a downgrade, without a verify button", async () => {
    mocked.domain.mockResolvedValue(
      make({
        available: false,
        upgrade_url: "https://ganek.io/pricing",
        domain: "careers.acme.com",
        status: "verified",
      }),
    );
    mocked.removeDomain.mockResolvedValue(
      make({ available: false, upgrade_url: "https://ganek.io/pricing" }),
    );
    render(<CustomDomainCard />);
    expect(await screen.findByText(/no longer includes custom domains/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(mocked.removeDomain).toHaveBeenCalled();
    expect(await screen.findByText(/part of the Team plan/)).toBeInTheDocument();
  });

  it("says so when the settings fail to load", async () => {
    mocked.domain.mockRejectedValue(new ApiError(500, "boom"));
    render(<CustomDomainCard />);
    expect(await screen.findByText(/Could not load/)).toBeInTheDocument();
  });
});

describe("CustomDomainCard in German", () => {
  const renderGerman = () =>
    render(
      <LocaleProvider>
        <CustomDomainCard />
      </LocaleProvider>,
    );

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.setItem("ganek.admin.locale", "de");
  });
  afterEach(() => window.localStorage.clear());

  it("adds a domain and shows the TXT record in German", async () => {
    mocked.domain.mockResolvedValue(make());
    mocked.setDomain.mockResolvedValue(pending);
    renderGerman();
    expect(await screen.findByText("Eigene Domain")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Eigene Domain"), "careers.acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Domain hinzufügen" }));
    expect(await screen.findByText("DNS ausstehend")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Domain hinzugefügt");
    expect(screen.getByText(/^Legen Sie diesen TXT-Eintrag/)).toBeInTheDocument();
    expect(screen.getByText("Typ")).toBeInTheDocument();
    expect(screen.getByText("Wert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "TXT-Name kopieren" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "TXT-Wert kopieren" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verifizieren" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Entfernen" })).toBeInTheDocument();
  });

  it("explains a downgraded domain in German", async () => {
    mocked.domain.mockResolvedValue(
      make({
        available: false,
        upgrade_url: "https://ganek.io/pricing",
        domain: "careers.acme.com",
        status: "verified",
      }),
    );
    renderGerman();
    expect(await screen.findByText("verifiziert")).toBeInTheDocument();
    expect(screen.getByText(/Inhaberschaft bestätigt/)).toBeInTheDocument();
    expect(screen.getByText(/enthält keine eigenen Domains mehr/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tarif upgraden" })).toHaveAttribute(
      "href",
      "https://ganek.io/pricing",
    );
  });

  it("says so in German when the settings fail to load", async () => {
    mocked.domain.mockRejectedValue(new ApiError(500, "boom"));
    renderGerman();
    expect(await screen.findByText(/konnten nicht geladen werden/)).toBeInTheDocument();
  });
});
