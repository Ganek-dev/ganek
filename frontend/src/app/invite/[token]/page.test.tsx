import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, publicInvites } from "@/lib/api";

import InviteAcceptPage from "./page";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "invite-tok" }),
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    publicInvites: { get: vi.fn(), accept: vi.fn() },
  };
});

const mocked = vi.mocked(publicInvites);

describe("InviteAcceptPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue({
      email: "sofia@x.dev",
      company_name: "Acme Labs",
      role: "member",
    });
    mocked.accept.mockResolvedValue({
      id: "u9",
      company_id: "c1",
      email: "sofia@x.dev",
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
