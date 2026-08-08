import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import SetupPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: { ...original.api, register: vi.fn() } };
});

const mocked = vi.mocked(api);

describe("SetupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.register.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy@acmelabs.io",
      has_password: true,
      role: "admin",
    });
  });

  it("previews the slug live as the company name is typed", async () => {
    render(<SetupPage />);
    expect(screen.getByText(/your careers page URL will show here/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs!");
    expect(screen.getByText(/acme-labs/)).toBeInTheDocument();
    expect(screen.getByText(/\.vetd\.dev/)).toBeInTheDocument();
  });

  it("creates the workspace and redirects to /admin", async () => {
    render(<SetupPage />);
    await userEvent.type(screen.getByLabelText("Work email"), "grumpy@acmelabs.io");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs");
    await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));

    await waitFor(() =>
      expect(mocked.register).toHaveBeenCalledWith({
        company_name: "Acme Labs",
        email: "grumpy@acmelabs.io",
        password: "correct-horse-battery",
      }),
    );
    expect(push).toHaveBeenCalledWith("/admin");
  });

  it("links back to login", () => {
    render(<SetupPage />);
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
  });
});
