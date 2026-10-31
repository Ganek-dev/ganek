import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, companyApi, type CompanyAdmin } from "@/lib/api";

import VerifyPage from "./page";

const replace = vi.fn();
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => search,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, verifyEmail: vi.fn() },
    companyApi: { ...original.companyApi, get: vi.fn() },
  };
});

const mocked = vi.mocked(api);
const mockedCompany = vi.mocked(companyApi);

const company: CompanyAdmin = {
  screening_questions: [],
  slug: "acme-labs",
  name: "Acme Labs",
  description: "",
  mode: "multi",
  smtp_configured: true,
  logo_url: null,
  website: null,
  socials: {},
  theme: {},
  settings: {},
};

describe("VerifyPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams({ token: "tok-1" });
    mocked.verifyEmail.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "a@b.dev",
      has_password: true,
      role: "admin",
    });
    mockedCompany.get.mockResolvedValue(company);
  });

  it("verifies the token and lands on the workspace-is-live page", async () => {
    render(<VerifyPage />);
    await waitFor(() => expect(mocked.verifyEmail).toHaveBeenCalledWith({ token: "tok-1" }));
    expect(
      await screen.findByRole("heading", { name: "Acme Labs is live" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/a@b\.dev is verified/)).toBeInTheDocument();
    // the careers URL is the share-ready thing a new admin wants first
    expect(screen.getByText(new RegExp(`${window.location.host}/c/acme-labs`))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy careers URL" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to your dashboard" })).toHaveAttribute(
      "href",
      "/admin",
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("still lands when the company lookup fails", async () => {
    mockedCompany.get.mockRejectedValueOnce(new Error("boom"));
    render(<VerifyPage />);
    expect(
      await screen.findByRole("heading", { name: "Your workspace is live" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to your dashboard" })).toHaveAttribute(
      "href",
      "/admin",
    );
  });

  it("shows the expired state on a bad token", async () => {
    mocked.verifyEmail.mockRejectedValueOnce(new Error("invalid or has expired"));
    render(<VerifyPage />);
    expect(await screen.findByRole("heading", { name: /didn't work/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a new signup" })).toHaveAttribute(
      "href",
      "/setup",
    );
  });

  it("fails immediately without a token", async () => {
    search = new URLSearchParams();
    render(<VerifyPage />);
    expect(await screen.findByRole("heading", { name: /didn't work/ })).toBeInTheDocument();
    expect(mocked.verifyEmail).not.toHaveBeenCalled();
  });
});
