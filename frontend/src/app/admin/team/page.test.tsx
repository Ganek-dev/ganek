import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { team, type TeamUser } from "@/lib/api";

import TeamPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, team: { list: vi.fn(), create: vi.fn(), update: vi.fn() } };
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

describe("TeamPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.list.mockResolvedValue([admin, member]);
    mocked.create.mockResolvedValue({ ...member, id: "u3", email: "new@x.dev" });
    mocked.update.mockResolvedValue({ ...member, role: "admin" });
  });

  it("lists members with display name, activity string, and count header", async () => {
    render(<TeamPage />);
    expect(await screen.findByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("Dana Kowalska")).toBeInTheDocument();
    expect(screen.getByText("admin@x.dev")).toBeInTheDocument();
    expect(screen.getByText("dana.kowalska@x.dev")).toBeInTheDocument();
    expect(screen.getByText("2 members")).toBeInTheDocument();
    expect(screen.getByText("active 1h ago")).toBeInTheDocument();
    expect(screen.getByText("never logged in")).toBeInTheDocument();
  });

  it("creates a member via the Add-member card", async () => {
    render(<TeamPage />);
    await userEvent.click(await screen.findByRole("button", { name: /Add member/ }));
    await userEvent.type(screen.getByLabelText("Email"), "new@x.dev");
    await userEvent.type(screen.getByLabelText("Password (min 10)"), "password12345");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() =>
      expect(mocked.create).toHaveBeenCalledWith("new@x.dev", "password12345", "member"),
    );
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
