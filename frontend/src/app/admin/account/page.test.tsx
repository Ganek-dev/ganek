import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import AccountPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/account",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, changePassword: vi.fn(), me: vi.fn() },
  };
});

const mocked = vi.mocked(api);

describe("AccountPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.changePassword.mockResolvedValue();
    mocked.me.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy.miner@acmelabs.io",
      role: "admin",
    });
  });

  it("renders the profile card with email and role from api.me()", async () => {
    render(<AccountPage />);
    expect(await screen.findByRole("textbox", { name: "Email" })).toHaveValue(
      "grumpy.miner@acmelabs.io",
    );
    expect(screen.getAllByText(/admin/i).length).toBeGreaterThan(0);
  });

  it("changes the password when confirmation matches", async () => {
    render(<AccountPage />);
    await userEvent.type(screen.getByLabelText("Current password"), "old-password-1");
    await userEvent.type(screen.getByLabelText("New password (min 10)"), "new-password-12");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "new-password-12");
    await userEvent.click(screen.getByRole("button", { name: "Update password" }));
    await waitFor(() =>
      expect(mocked.changePassword).toHaveBeenCalledWith("old-password-1", "new-password-12"),
    );
    expect(await screen.findByText("Password changed.")).toBeInTheDocument();
  });

  it("rejects mismatched confirmation without calling the API", async () => {
    render(<AccountPage />);
    await userEvent.type(screen.getByLabelText("Current password"), "old-password-1");
    await userEvent.type(screen.getByLabelText("New password (min 10)"), "new-password-12");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "different-98765");
    await userEvent.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(mocked.changePassword).not.toHaveBeenCalled();
  });
});
