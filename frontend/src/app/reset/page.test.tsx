import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import ResetPasswordPage from "./page";

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
    api: { ...original.api, forgotPassword: vi.fn(), resetPassword: vi.fn() },
  };
});

const mocked = vi.mocked(api);

describe("ResetPasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams();
    mocked.forgotPassword.mockResolvedValue(undefined);
    mocked.resetPassword.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "you@company.com",
      has_password: true,
      role: "admin",
    });
  });

  it("requests a link and claims success without revealing accounts", async () => {
    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("Email"), "you@company.com");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));

    await waitFor(() =>
      expect(mocked.forgotPassword).toHaveBeenCalledWith({ email: "you@company.com" }),
    );
    expect(screen.getByRole("heading", { name: /Check your inbox/ })).toBeInTheDocument();
    expect(screen.getByText(/If that address has a workspace account/)).toBeInTheDocument();
  });

  it("claims success even when the request fails (no enumeration)", async () => {
    mocked.forgotPassword.mockRejectedValueOnce(new Error("rate limited"));
    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("Email"), "nobody@company.com");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("heading", { name: /Check your inbox/ })).toBeInTheDocument();
  });

  it("sets a new password from a token link and redirects", async () => {
    search = new URLSearchParams({ token: "tok-123" });
    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("New password"), "a-brand-new-password");
    await userEvent.type(screen.getByLabelText("Repeat password"), "a-brand-new-password");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));

    await waitFor(() =>
      expect(mocked.resetPassword).toHaveBeenCalledWith({
        token: "tok-123",
        new_password: "a-brand-new-password",
      }),
    );
    expect(push).toHaveBeenCalledWith("/admin");
  });

  it("rejects mismatched passwords locally", async () => {
    search = new URLSearchParams({ token: "tok-123" });
    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("New password"), "a-brand-new-password");
    await userEvent.type(screen.getByLabelText("Repeat password"), "a-different-password");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/don't match/);
    expect(mocked.resetPassword).not.toHaveBeenCalled();
  });

  it("surfaces an expired-link error with a way to start over", async () => {
    search = new URLSearchParams({ token: "tok-old" });
    mocked.resetPassword.mockRejectedValueOnce(
      new Error("This reset link is invalid or has expired — request a new one"),
    );
    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("New password"), "a-brand-new-password");
    await userEvent.type(screen.getByLabelText("Repeat password"), "a-brand-new-password");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/invalid or has expired/);
    expect(screen.getByRole("link", { name: "Request a new link" })).toHaveAttribute(
      "href",
      "/reset",
    );
  });
});
