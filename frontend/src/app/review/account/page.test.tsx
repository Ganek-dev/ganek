import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import ReviewAccountPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/review/account",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      me: vi.fn(),
      updateProfile: vi.fn(),
      providers: vi.fn(),
      availability: { get: vi.fn(), set: vi.fn() },
    },
  };
});

const mocked = vi.mocked(api, true);
const reviewer = {
  id: "u2",
  company_id: "c1",
  email: "max@acme.example",
  has_password: true,
  role: "reviewer" as const,
  display_name: "Max Berger",
  display_label: "Max Berger",
  mfa_enabled: false,
};

describe("ReviewAccountPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.me.mockResolvedValue(reviewer);
    mocked.providers.mockResolvedValue({ google: false, mode: "single" });
    mocked.availability.get.mockResolvedValue({
      timezone: "",
      is_default: true,
      location: "Room 2",
      days: {},
    });
  });

  it("edits the display name and shows 2FA and the interview location, no admin tabs", async () => {
    mocked.updateProfile.mockResolvedValue({ ...reviewer, display_name: "Maxi" });
    render(<ReviewAccountPage />);
    await waitFor(() => expect(screen.getByLabelText("Display name")).toHaveValue("Max Berger"));
    const name = screen.getByLabelText("Display name");
    await userEvent.clear(name);
    await userEvent.type(name, "Maxi");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(mocked.updateProfile).toHaveBeenCalledWith("Maxi"));
    expect(await screen.findByText(/two-factor|Two-factor/i)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Room 2")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Settings sections" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to candidates/ })).toHaveAttribute(
      "href",
      "/review",
    );
  });
});
