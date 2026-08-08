import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import LoginPage from "./page";

const push = vi.fn();
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => search,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, login: vi.fn(), providers: vi.fn() },
  };
});

const mocked = vi.mocked(api);

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams();
    mocked.providers.mockResolvedValue({ google: false });
    mocked.login.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "you@company.com",
      has_password: true,
      role: "admin",
    });
  });

  it("shows the auth shell without Google when the instance has no OAuth", async () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: /Log in to your workspace/ })).toBeInTheDocument();
    await waitFor(() => expect(mocked.providers).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /Continue with Google/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Forgot?" })).toHaveAttribute("href", "/reset");
    expect(screen.getByRole("link", { name: /Create a workspace/ })).toHaveAttribute(
      "href",
      "/setup",
    );
  });

  it("shows the Google button when the instance has OAuth configured", async () => {
    mocked.providers.mockResolvedValue({ google: true });
    render(<LoginPage />);
    const link = await screen.findByRole("link", { name: /Continue with Google/ });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start");
    expect(screen.getByText(/or with email/i)).toBeInTheDocument();
  });

  it.each([
    ["use-password", /log in with your password/i],
    ["account-disabled", /deactivated/i],
    ["google-failed", /didn't complete/i],
  ])("surfaces the %s oauth error", async (code, copy) => {
    search = new URLSearchParams({ error: code });
    render(<LoginPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy);
  });

  it("ignores unknown error codes", async () => {
    search = new URLSearchParams({ error: "some-new-thing" });
    render(<LoginPage />);
    await waitFor(() => expect(mocked.providers).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("submits credentials and redirects on success", async () => {
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "you@company.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() =>
      expect(mocked.login).toHaveBeenCalledWith({
        email: "you@company.com",
        password: "correct-horse-battery",
      }),
    );
    expect(push).toHaveBeenCalledWith("/admin");
  });

  it("shows the error message on failed login", async () => {
    mocked.login.mockRejectedValueOnce(new Error("Invalid credentials"));
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "wrong@company.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
  });
});
