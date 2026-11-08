import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type UserOut } from "@/lib/api";

import { PlanLimitNotice } from "./PlanLimitNotice";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: { ...original.api, me: vi.fn() } };
});

const mocked = vi.mocked(api);

function user(role: UserOut["role"]): UserOut {
  return {
    id: "u1",
    company_id: "c1",
    email: "x@acme.dev",
    has_password: true,
    role,
  };
}

const limit = { limit: 1, upgradeUrl: "https://billing.example/upgrade" };

describe("PlanLimitNotice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an admin the upgrade link", async () => {
    mocked.me.mockResolvedValue(user("admin"));
    render(<PlanLimitNotice limit={limit} />);
    const link = await screen.findByRole("link", { name: "Upgrade plan" });
    expect(link).toHaveAttribute("href", "https://billing.example/upgrade");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your plan allows 1 live job. Close a job or upgrade the plan to publish another.",
    );
  });

  it("tells a recruiter to ask their admin, without a link", async () => {
    mocked.me.mockResolvedValue(user("member"));
    render(<PlanLimitNotice limit={limit} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("ask your admin");
    await vi.waitFor(() => expect(mocked.me).toHaveBeenCalled());
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("falls back to the recruiter wording when the role is unknown", async () => {
    mocked.me.mockRejectedValue(new Error("offline"));
    render(<PlanLimitNotice limit={limit} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("ask your admin");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
