import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, type CompanySeat } from "@/lib/api";

import { CompanySwitcher, homeFor } from "./CompanySwitcher";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, companies: vi.fn(), switchCompany: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);

const ACME: CompanySeat = {
  company_id: "c1",
  name: "Acme",
  slug: "acme",
  role: "admin",
  active: true,
};
const GLOBEX: CompanySeat = {
  company_id: "c2",
  name: "Globex",
  slug: "globex",
  role: "reviewer",
  active: false,
};

describe("CompanySwitcher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the fallback for a single-seat user", async () => {
    mockedApi.companies.mockResolvedValue([ACME]);
    render(<CompanySwitcher fallback={<span>Acme plain</span>} />);
    await waitFor(() => expect(mockedApi.companies).toHaveBeenCalled());
    expect(screen.getByText("Acme plain")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("lists every seat with its role, the active one selected", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    render(<CompanySwitcher fallback={<span>Acme plain</span>} />);
    const select = await screen.findByRole("combobox", { name: "Company" });
    expect(select).toHaveValue("c1");
    expect(screen.getByRole("option", { name: "Acme (Admin)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Globex (Reviewer)" })).toBeInTheDocument();
    expect(screen.queryByText("Acme plain")).not.toBeInTheDocument();
  });

  it("switches and hard-navigates to the new seat's home", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    mockedApi.switchCompany.mockResolvedValue({
      id: "u1",
      company_id: "c2",
      email: "max@acme.dev",
      role: "reviewer",
      has_password: true,
    });
    const navigate = vi.fn();
    render(<CompanySwitcher navigate={navigate} />);
    await userEvent.selectOptions(await screen.findByRole("combobox"), "c2");
    expect(mockedApi.switchCompany).toHaveBeenCalledWith("c2");
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/review"));
  });

  it("shows the server's reason when the switch is refused", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    mockedApi.switchCompany.mockRejectedValue(new ApiError(403, "Account suspended: unpaid"));
    const navigate = vi.fn();
    render(<CompanySwitcher navigate={navigate} />);
    const select = await screen.findByRole("combobox");
    await userEvent.selectOptions(select, "c2");
    expect(await screen.findByRole("alert")).toHaveTextContent("Account suspended: unpaid");
    expect(navigate).not.toHaveBeenCalled();
    expect(select).not.toBeDisabled();
  });

  it("stays hidden and asks nothing while impersonating", () => {
    render(<CompanySwitcher impersonating fallback={<span>Acme plain</span>} />);
    expect(mockedApi.companies).not.toHaveBeenCalled();
    expect(screen.getByText("Acme plain")).toBeInTheDocument();
  });

  it("falls back quietly when the seat list fails", async () => {
    mockedApi.companies.mockRejectedValue(new ApiError(500, "boom"));
    render(<CompanySwitcher fallback={<span>Acme plain</span>} />);
    await waitFor(() => expect(mockedApi.companies).toHaveBeenCalled());
    expect(screen.getByText("Acme plain")).toBeInTheDocument();
  });

  it("sends admins and members to /admin, reviewers to /review", () => {
    expect(homeFor("admin")).toBe("/admin");
    expect(homeFor("member")).toBe("/admin");
    expect(homeFor("reviewer")).toBe("/review");
  });
});
