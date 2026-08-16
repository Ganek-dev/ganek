import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, publicInvites } from "@/lib/api";

import InviteAcceptPage from "./page";

const push = vi.fn();
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "invite-tok" }),
  useRouter: () => ({ push }),
  useSearchParams: () => search,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, providers: vi.fn() },
    publicInvites: { get: vi.fn(), accept: vi.fn() },
  };
});

const mocked = vi.mocked(publicInvites);
const mockedApi = vi.mocked(api);

describe("InviteAcceptPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams();
    mockedApi.providers.mockResolvedValue({ google: false, mode: "single" });
    mocked.get.mockResolvedValue({
      email: "sofia@x.dev",
      company_name: "Acme Labs",
      role: "member",
    });
    mocked.accept.mockResolvedValue({
      id: "u9",
      company_id: "c1",
      email: "sofia@x.dev",
      has_password: true,
      role: "member",
    });
  });

  it("shows the invite context and accepts with a password", async () => {
    render(<InviteAcceptPage />);
    expect(await screen.findByRole("heading", { name: "Join Acme Labs" })).toBeInTheDocument();
    expect(screen.getByText(/invited as a Member/)).toBeInTheDocument();
    expect(screen.getByText("sofia@x.dev")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Password"), "a-new-password-1");
    await userEvent.click(screen.getByRole("button", { name: "Accept invite" }));
    await waitFor(() =>
      expect(mocked.accept).toHaveBeenCalledWith("invite-tok", "a-new-password-1"),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin"));
  });

  it("names the admin role in the subtitle", async () => {
    mocked.get.mockResolvedValue({
      email: "sofia@x.dev",
      company_name: "Acme Labs",
      role: "admin",
    });
    render(<InviteAcceptPage />);
    expect(await screen.findByText(/invited as an Admin/)).toBeInTheDocument();
  });

  it("renders the expired state on a 410", async () => {
    mocked.get.mockRejectedValue(new ApiError(410, "This invite has expired"));
    render(<InviteAcceptPage />);
    expect(
      await screen.findByRole("heading", { name: "This invite has expired" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("renders the invalid state on a 404", async () => {
    mocked.get.mockRejectedValue(new ApiError(404, "Invite not found"));
    render(<InviteAcceptPage />);
    expect(
      await screen.findByRole("heading", { name: "Invite not found" }),
    ).toBeInTheDocument();
  });

  it("surfaces an email conflict from accept without killing the form", async () => {
    mocked.accept.mockRejectedValue(
      new ApiError(409, "An account with this email already exists"),
    );
    render(<InviteAcceptPage />);
    await userEvent.type(await screen.findByLabelText("Password"), "a-new-password-1");
    await userEvent.click(screen.getByRole("button", { name: "Accept invite" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An account with this email already exists",
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("offers Google accept carrying the invite token when OAuth is configured", async () => {
    mockedApi.providers.mockResolvedValue({ google: true, mode: "single" });
    render(<InviteAcceptPage />);
    const link = await screen.findByRole("link", { name: /Continue with Google/ });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start?invite=invite-tok");
    expect(screen.getByText(/or set a password/i)).toBeInTheDocument();
  });

  it("hides the Google option when the instance has no OAuth", async () => {
    render(<InviteAcceptPage />);
    await screen.findByRole("heading", { name: "Join Acme Labs" });
    await waitFor(() => expect(mockedApi.providers).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /Continue with Google/ })).not.toBeInTheDocument();
  });

  it.each([
    ["google-email-mismatch", /doesn't match this invite/i],
    ["email-taken", /already exists/i],
    ["google-invalid", /didn't complete/i],
  ])("surfaces the %s google error", async (code, copy) => {
    search = new URLSearchParams({ error: code });
    render(<InviteAcceptPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy);
  });

  it("flips to the expired state when accept returns 410", async () => {
    mocked.accept.mockRejectedValue(new ApiError(410, "This invite has expired"));
    render(<InviteAcceptPage />);
    await userEvent.type(await screen.findByLabelText("Password"), "a-new-password-1");
    await userEvent.click(screen.getByRole("button", { name: "Accept invite" }));
    expect(
      await screen.findByRole("heading", { name: "This invite has expired" }),
    ).toBeInTheDocument();
  });
});
