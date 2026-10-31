import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import AccountPage from "./page";

let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/account",
  useSearchParams: () => search,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      changePassword: vi.fn(),
      updateProfile: vi.fn(),
      me: vi.fn(),
      providers: vi.fn(),
      availability: { get: vi.fn(), set: vi.fn() },
    },
  };
});

const mocked = vi.mocked(api, true);

describe("AccountPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams();
    mocked.providers.mockResolvedValue({ google: false, mode: "single" });
    mocked.availability.get.mockResolvedValue({
      timezone: "",
      is_default: true,
      location: "",
      days: Object.fromEntries(
        ["mon", "tue", "wed", "thu", "fri"].map((d) => [d, { start: "09:00", end: "17:00" }]),
      ),
    });
    mocked.changePassword.mockResolvedValue();
    mocked.me.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy.miner@acmelabs.io",
      has_password: true,
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

  it("has no calendar card even when google sign-in is configured", async () => {
    mocked.providers.mockResolvedValue({ google: true, mode: "single" });
    render(<AccountPage />);
    await screen.findByRole("textbox", { name: "Email" });
    expect(screen.queryByText(/Google Calendar/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Connect/ })).not.toBeInTheDocument();
  });

  it("shows the Google note instead of the form for google-only accounts", async () => {
    mocked.me.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy.miner@gmail.com",
      has_password: false,
      role: "admin",
    });
    render(<AccountPage />);
    expect(await screen.findByText(/You sign in with Google/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update password" })).not.toBeInTheDocument();
  });

  it("saves the display name and shows the server's label as the placeholder", async () => {
    mocked.me.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy.miner@acmelabs.io",
      has_password: true,
      role: "admin",
      display_name: null,
      display_label: "Grumpy Miner",
    });
    mocked.updateProfile.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy.miner@acmelabs.io",
      has_password: true,
      role: "admin",
      display_name: "The Miner",
      display_label: "The Miner",
    });
    render(<AccountPage />);
    // the placeholder is the server's label, so it appears once api.me() resolved
    const field = await screen.findByPlaceholderText("Grumpy Miner");
    expect(field).toBe(screen.getByLabelText("Display name"));
    await userEvent.type(field, "The Miner");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(mocked.updateProfile).toHaveBeenCalledWith("The Miner"));
    expect(await screen.findByRole("button", { name: "Saved" })).toBeInTheDocument();
  });

  it("locks password, two-factor, sessions and Google on a demo instance", async () => {
    mocked.providers.mockResolvedValue({ google: true, mode: "single", demo: true });
    render(<AccountPage />);
    expect(
      await screen.findByText(/Password changes are off on the demo workspace/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Current password")).toBeNull();
    expect(screen.getByRole("button", { name: "Set up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sign out everywhere" })).toBeDisabled();
  });
});
