import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import SetupPage from "./page";

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
    api: {
      ...original.api,
      register: vi.fn(),
      googleSignup: vi.fn(),
      providers: vi.fn(),
    },
  };
});

const mocked = vi.mocked(api);

/** payload.timestamp.signature shape; only the payload segment is decoded client-side */
function gsToken(email: string): string {
  return `${btoa(JSON.stringify({ sub: "sub-1", email }))}.ts.sig`;
}

const googleUser = {
  id: "u1",
  company_id: "c1",
  email: "grumpy@gmail.com",
  has_password: false,
  role: "admin" as const,
};

describe("SetupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams();
    mocked.providers.mockResolvedValue({ google: false });
    mocked.googleSignup.mockResolvedValue(googleUser);
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

  it("offers Google signup when the instance has OAuth configured", async () => {
    mocked.providers.mockResolvedValue({ google: true });
    render(<SetupPage />);
    const link = await screen.findByRole("link", { name: /Sign up with Google/ });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start");
  });

  describe("with a Google signup token", () => {
    beforeEach(() => {
      search = new URLSearchParams({ gs: gsToken("grumpy@gmail.com") });
    });

    it("shows the Google onboarding variant without password fields", () => {
      render(<SetupPage />);
      expect(screen.getByText(/Signing up with Google as/)).toBeInTheDocument();
      expect(screen.getByText("grumpy@gmail.com")).toBeInTheDocument();
      expect(screen.queryByLabelText("Work email")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: /Sign up with Google/ })).not.toBeInTheDocument();
    });

    it("completes signup with the token and company name", async () => {
      render(<SetupPage />);
      await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs");
      await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));

      await waitFor(() =>
        expect(mocked.googleSignup).toHaveBeenCalledWith({
          token: gsToken("grumpy@gmail.com"),
          company_name: "Acme Labs",
        }),
      );
      expect(push).toHaveBeenCalledWith("/admin");
    });

    it("shows the restart path when the token expired", async () => {
      mocked.googleSignup.mockRejectedValueOnce(
        new Error("This Google signup link has expired — sign in with Google again"),
      );
      render(<SetupPage />);
      await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs");
      await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/session expired/i);
      expect(screen.getByRole("link", { name: /Sign in with Google again/ })).toHaveAttribute(
        "href",
        "/login",
      );
    });

    it("surfaces other signup errors inline", async () => {
      mocked.googleSignup.mockRejectedValueOnce(
        new Error("Registration is closed on this instance"),
      );
      render(<SetupPage />);
      await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs");
      await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/Registration is closed/);
    });
  });
});
