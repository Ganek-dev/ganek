import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { team, type TeamInvite, type TeamUser } from "@/lib/api";

import TeamPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    team: {
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      listInvites: vi.fn(),
      invite: vi.fn(),
      resendInvite: vi.fn(),
      revokeInvite: vi.fn(),
    },
  };
});

const mocked = vi.mocked(team);

const admin: TeamUser = {
  id: "u1",
  email: "admin@x.dev",
  role: "admin",
  is_active: true,
  last_login_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  created_at: "2026-07-01T00:00:00Z",
};
const member: TeamUser = {
  id: "u2",
  email: "dana.kowalska@x.dev",
  role: "member",
  is_active: true,
  last_login_at: null,
  created_at: "2026-07-02T00:00:00Z",
};
const pending: TeamInvite = {
  id: "i1",
  email: "sofia@x.dev",
  role: "member",
  created_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
  expires_at: new Date(Date.now() + 5 * 86_400_000).toISOString(),
};

describe("TeamPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.list.mockResolvedValue([admin, member]);
    mocked.listInvites.mockResolvedValue([pending]);
    mocked.invite.mockResolvedValue({ ...pending, id: "i2", email: "new@x.dev" });
    mocked.resendInvite.mockResolvedValue(pending);
    mocked.revokeInvite.mockResolvedValue(undefined);
    mocked.update.mockResolvedValue({ ...member, role: "admin" });
  });

  it("lists members with display name, activity string, and count header", async () => {
    render(<TeamPage />);
    expect(await screen.findByText("Admin", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Dana Kowalska")).toBeInTheDocument();
    expect(screen.getByText("admin@x.dev")).toBeInTheDocument();
    expect(screen.getByText("dana.kowalska@x.dev")).toBeInTheDocument();
    expect(screen.getByText("2 members · 1 pending invite")).toBeInTheDocument();
    expect(screen.getByText("active 1h ago")).toBeInTheDocument();
    expect(screen.getByText("never logged in")).toBeInTheDocument();
  });

  it("shows the pending invite row with meta line and pending pill", async () => {
    render(<TeamPage />);
    expect(await screen.findByText("sofia@x.dev")).toBeInTheDocument();
    expect(screen.getByText("invite pending")).toBeInTheDocument();
    expect(screen.getByText("invited 2d ago · Member · expires in 5d")).toBeInTheDocument();
  });

  it("sends an invite from the invite bar", async () => {
    render(<TeamPage />);
    await screen.findByText("Dana Kowalska");
    await userEvent.type(screen.getByLabelText("Invite email"), "new@x.dev");
    await userEvent.selectOptions(screen.getByLabelText("Invite role"), "member");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));
    await waitFor(() => expect(mocked.invite).toHaveBeenCalledWith("new@x.dev", "member"));
    expect(await screen.findByRole("status")).toHaveTextContent("Invite sent to new@x.dev");
  });

  it("surfaces API conflicts when sending an invite", async () => {
    mocked.invite.mockRejectedValue(new Error("This email already has a pending invite"));
    render(<TeamPage />);
    await screen.findByText("Dana Kowalska");
    await userEvent.type(screen.getByLabelText("Invite email"), "sofia@x.dev");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This email already has a pending invite",
    );
  });

  it("resends a pending invite", async () => {
    render(<TeamPage />);
    await screen.findByText("sofia@x.dev");
    await userEvent.click(screen.getByRole("button", { name: "Resend" }));
    await waitFor(() => expect(mocked.resendInvite).toHaveBeenCalledWith("i1"));
    expect(await screen.findByRole("status")).toHaveTextContent("Invite re-sent to sofia@x.dev");
  });

  it("revokes a pending invite", async () => {
    render(<TeamPage />);
    await screen.findByText("sofia@x.dev");
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(mocked.revokeInvite).toHaveBeenCalledWith("i1"));
  });

  it("promotes a member to admin via the role select", async () => {
    render(<TeamPage />);
    const select = await screen.findByLabelText("Role for dana.kowalska@x.dev");
    await userEvent.selectOptions(select, "admin");
    await waitFor(() => expect(mocked.update).toHaveBeenCalledWith("u2", { role: "admin" }));
  });

  it("deactivates a user through the row action menu", async () => {
    render(<TeamPage />);
    await screen.findByText("Dana Kowalska");
    await userEvent.click(
      screen.getByRole("button", { name: "Actions for dana.kowalska@x.dev" }),
    );
    const menu = screen.getByRole("menu");
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Deactivate" }));
    await waitFor(() => expect(mocked.update).toHaveBeenCalledWith("u2", { is_active: false }));
  });
});
