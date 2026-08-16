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
      me: vi.fn(),
      providers: vi.fn(),
      googleCalendar: { status: vi.fn(), disconnect: vi.fn() },
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
    mocked.googleCalendar.status.mockResolvedValue({
      connected: false,
      google_email: null,
      needs_reconnect: false,
    });
    mocked.googleCalendar.disconnect.mockResolvedValue();
    mocked.availability.get.mockResolvedValue({
      timezone: "",
      is_default: true,
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

  it("hides the calendar card when the instance has no google oauth", async () => {
    render(<AccountPage />);
    await screen.findByRole("textbox", { name: "Email" });
    expect(screen.queryByText("Google Calendar")).not.toBeInTheDocument();
  });

  it("offers Connect when google is configured but not connected", async () => {
    mocked.providers.mockResolvedValue({ google: true, mode: "single" });
    render(<AccountPage />);
    const link = await screen.findByRole("link", { name: "Connect Google Calendar" });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/calendar/connect");
  });

  it("shows the connected state and disconnects", async () => {
    mocked.providers.mockResolvedValue({ google: true, mode: "single" });
    mocked.googleCalendar.status.mockResolvedValue({
      connected: true,
      google_email: "grumpy@gmail.com",
      needs_reconnect: false,
    });
    render(<AccountPage />);
    expect(await screen.findByText("grumpy@gmail.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(mocked.googleCalendar.disconnect).toHaveBeenCalled());
    expect(
      await screen.findByRole("link", { name: "Connect Google Calendar" }),
    ).toBeInTheDocument();
  });

  it("prompts to reconnect when calendar access expired", async () => {
    mocked.providers.mockResolvedValue({ google: true, mode: "single" });
    mocked.googleCalendar.status.mockResolvedValue({
      connected: true,
      google_email: "grumpy@gmail.com",
      needs_reconnect: true,
    });
    render(<AccountPage />);
    expect(await screen.findByText(/access expired or was revoked/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "reconnect" })).toHaveAttribute(
      "href",
      "/api/v1/auth/google/calendar/connect",
    );
  });

  it("surfaces the wrong-account notice from the callback redirect", async () => {
    mocked.providers.mockResolvedValue({ google: true, mode: "single" });
    search = new URLSearchParams({ calendar: "wrong-account" });
    render(<AccountPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/different vetd user/i);
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
});
