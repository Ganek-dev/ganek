import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";

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
      resendVerification: vi.fn(),
      googleSignup: vi.fn(),
      googleSignupPending: vi.fn(),
      providers: vi.fn(),
    },
  };
});

const mocked = vi.mocked(api);

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
    mocked.providers.mockResolvedValue({ google: false, mode: "single" });
    mocked.googleSignup.mockResolvedValue(googleUser);
    mocked.googleSignupPending.mockResolvedValue({ email: "grumpy@gmail.com" });
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
    // slug-bearing /c/ path - resolves on any deployment, unlike a ganek.dev
    // subdomain a self-hosted instance doesn't have
    expect(screen.getByText(new RegExp(`${window.location.host}/c/acme-labs`))).toBeInTheDocument();
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
        altcha: null,
      }),
    );
    expect(push).toHaveBeenCalledWith("/admin");
  });

  it("holds at check-your-inbox when the signup needs verification", async () => {
    mocked.register.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "grumpy@acmelabs.io",
      has_password: true,
      role: "admin",
      pending_verification: true,
    });
    mocked.resendVerification.mockResolvedValue(undefined);
    render(<SetupPage />);
    await userEvent.type(screen.getByLabelText("Work email"), "grumpy@acmelabs.io");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs");
    await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));

    expect(
      await screen.findByRole("heading", { name: "Check your inbox" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/grumpy@acmelabs\.io/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Resend the link" }));
    await waitFor(() =>
      expect(mocked.resendVerification).toHaveBeenCalledWith({ email: "grumpy@acmelabs.io" }),
    );
    expect(screen.getByRole("button", { name: "Link resent" })).toBeDisabled();
  });

  describe("what you get (multi mode)", () => {
    const limits = { active_jobs: 50, applications_per_hour: 100, emails_per_day: 500 };

    it("lists the instance limits and the activation step", async () => {
      mocked.providers.mockResolvedValue({ google: false, mode: "multi", limits });
      render(<SetupPage />);
      expect(await screen.findByRole("heading", { name: "What you get" })).toBeInTheDocument();
      expect(
        screen.getByText(/up to 50 open jobs, 100 applications an hour and 500 candidate emails a day/i),
      ).toBeInTheDocument();
      expect(screen.getByText(/we email you a link to activate it/i)).toBeInTheDocument();
    });

    it("drops limits that are off and says so when none apply", async () => {
      mocked.providers.mockResolvedValue({
        google: false,
        mode: "multi",
        limits: { active_jobs: 0, applications_per_hour: 100, emails_per_day: 0 },
      });
      render(<SetupPage />);
      expect(await screen.findByText(/up to 100 applications an hour/i)).toBeInTheDocument();
      expect(screen.queryByText(/open jobs/)).not.toBeInTheDocument();
    });

    it("says there are no limits when every guard is off", async () => {
      mocked.providers.mockResolvedValue({
        google: false,
        mode: "multi",
        limits: { active_jobs: 0, applications_per_hour: 0, emails_per_day: 0 },
      });
      render(<SetupPage />);
      expect(await screen.findByText(/no usage limits on this instance/i)).toBeInTheDocument();
    });

    it("shows the panel on the Google onboarding step too", async () => {
      search = new URLSearchParams({ google: "pending" });
      mocked.providers.mockResolvedValue({ google: true, mode: "multi", limits });
      render(<SetupPage />);
      expect(await screen.findByRole("heading", { name: "What you get" })).toBeInTheDocument();
      expect(await screen.findByText("grumpy@gmail.com")).toBeInTheDocument();
    });

    it("stays hidden on a single-company instance", async () => {
      render(<SetupPage />);
      await waitFor(() => expect(mocked.providers).toHaveBeenCalled());
      expect(screen.queryByRole("heading", { name: "What you get" })).not.toBeInTheDocument();
    });
  });

  it("links back to login", () => {
    render(<SetupPage />);
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
  });

  it("offers Google signup when the instance has OAuth configured", async () => {
    mocked.providers.mockResolvedValue({ google: true, mode: "single" });
    render(<SetupPage />);
    const link = await screen.findByRole("link", { name: /Sign up with Google/ });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start");
  });

  describe("with a pending Google signup (?google=pending)", () => {
    beforeEach(() => {
      search = new URLSearchParams({ google: "pending" });
    });

    it("shows the Google onboarding variant without password fields", async () => {
      render(<SetupPage />);
      expect(screen.getByText(/Signing up with Google as/)).toBeInTheDocument();
      // the vouched-for email comes from the server, never from the URL
      expect(await screen.findByText("grumpy@gmail.com")).toBeInTheDocument();
      expect(mocked.googleSignupPending).toHaveBeenCalled();
      expect(screen.queryByLabelText("Work email")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: /Sign up with Google/ })).not.toBeInTheDocument();
    });

    it("completes signup with just the company name", async () => {
      render(<SetupPage />);
      await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs");
      await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));

      await waitFor(() =>
        expect(mocked.googleSignup).toHaveBeenCalledWith({ company_name: "Acme Labs" }),
      );
      expect(push).toHaveBeenCalledWith("/admin");
    });

    it("shows the restart path when the pending session already expired", async () => {
      mocked.googleSignupPending.mockRejectedValueOnce(
        new ApiError(410, "This Google signup session has expired - sign in with Google again"),
      );
      render(<SetupPage />);

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/session expired/i);
      expect(screen.getByRole("link", { name: /Sign in with Google again/ })).toHaveAttribute(
        "href",
        "/login",
      );
      expect(screen.getByRole("button", { name: "Create workspace" })).toBeDisabled();
    });

    it("shows the restart path when the session expires at submit time", async () => {
      mocked.googleSignup.mockRejectedValueOnce(
        new Error("This Google signup session has expired - sign in with Google again"),
      );
      render(<SetupPage />);
      await userEvent.type(screen.getByLabelText("Company name"), "Acme Labs");
      await userEvent.click(screen.getByRole("button", { name: "Create workspace" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/session expired/i);
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
