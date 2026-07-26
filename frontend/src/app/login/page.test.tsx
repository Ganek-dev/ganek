import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import LoginPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: { ...original.api, login: vi.fn() } };
});

const mocked = vi.mocked(api);

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.login.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "you@company.com",
      role: "admin",
    });
  });

  it("shows the auth shell with Google placeholder and Forgot link", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: /Log in to your workspace/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Continue with Google/ })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Forgot?" })).toHaveAttribute("href", "/reset");
    expect(screen.getByRole("link", { name: /Create a workspace/ })).toHaveAttribute(
      "href",
      "/setup",
    );
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
