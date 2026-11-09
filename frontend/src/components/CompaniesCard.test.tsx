import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, type CompanySeat, type UserOut } from "@/lib/api";

import { CompaniesCard } from "./CompaniesCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, companies: vi.fn(), leaveCompany: vi.fn() },
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

function user(over: Partial<UserOut>): UserOut {
  return {
    id: "u1",
    company_id: "c1",
    email: "a@acme.dev",
    role: "admin",
    has_password: true,
    ...over,
  };
}

describe("CompaniesCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing for a single-seat user", async () => {
    mockedApi.companies.mockResolvedValue([ACME]);
    const { container } = render(<CompaniesCard />);
    await waitFor(() => expect(mockedApi.companies).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while impersonating and does not fetch", () => {
    const { container } = render(<CompaniesCard impersonating />);
    expect(container).toBeEmptyDOMElement();
    expect(mockedApi.companies).not.toHaveBeenCalled();
  });

  it("lists every seat with its role and marks the active one", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    render(<CompaniesCard />);
    expect(await screen.findByText("Your companies")).toBeInTheDocument();
    expect(screen.getByText("Admin · active now")).toBeInTheDocument();
    expect(screen.getByText("Reviewer")).toBeInTheDocument();
  });

  it("leaves another company after confirming and drops it from the list", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    mockedApi.leaveCompany.mockResolvedValue(user({}));
    const navigate = vi.fn();
    render(<CompaniesCard navigate={navigate} />);
    await userEvent.click(await screen.findByRole("button", { name: "Leave Globex" }));
    expect(screen.getByText(/You lose access to its jobs and candidates/)).toBeInTheDocument();
    expect(mockedApi.leaveCompany).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Leave Globex" }));
    expect(mockedApi.leaveCompany).toHaveBeenCalledWith("c2");
    await waitFor(() => expect(screen.queryByText("Globex")).not.toBeInTheDocument());
    expect(navigate).not.toHaveBeenCalled();
  });

  it("cancel closes the confirm without leaving", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    render(<CompaniesCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Leave Globex" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/You lose access/)).not.toBeInTheDocument();
    expect(mockedApi.leaveCompany).not.toHaveBeenCalled();
  });

  it("leaving the active company hard-navigates to the next seat's home", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    mockedApi.leaveCompany.mockResolvedValue(user({ company_id: "c2", role: "reviewer" }));
    const navigate = vi.fn();
    render(<CompaniesCard navigate={navigate} />);
    await userEvent.click(await screen.findByRole("button", { name: "Leave Acme" }));
    await userEvent.click(screen.getByRole("button", { name: "Leave Acme" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/review"));
  });

  it("shows the server's refusal and keeps the seat", async () => {
    mockedApi.companies.mockResolvedValue([ACME, GLOBEX]);
    mockedApi.leaveCompany.mockRejectedValue(
      new ApiError(409, "You are the last admin there. Make someone else an admin first"),
    );
    render(<CompaniesCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Leave Acme" }));
    await userEvent.click(screen.getByRole("button", { name: "Leave Acme" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You are the last admin there");
    expect(screen.getByText("Acme")).toBeInTheDocument();
  });
});
