import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type UserOut } from "@/lib/api";

import { TwoFactorCard } from "./TwoFactorCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      mfa: { enrol: vi.fn(), confirm: vi.fn(), disable: vi.fn() },
      signOutEverywhere: vi.fn(),
    },
  };
});

const mocked = vi.mocked(api, true);

function user(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: "u1",
    company_id: "c1",
    email: "grumpy.miner@acmelabs.io",
    has_password: true,
    role: "admin",
    mfa_enabled: false,
    recovery_codes_left: 0,
    ...overrides,
  };
}

describe("TwoFactorCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.mfa.enrol.mockResolvedValue({
      secret: "ABCDEFGHIJKLMNOP",
      otpauth_uri: "otpauth://totp/Ganek%3Agrumpy.miner%40acmelabs.io?secret=ABCDEFGHIJKLMNOP",
    });
    mocked.mfa.confirm.mockResolvedValue({ recovery_codes: ["aaaaa-bbbbb", "ccccc-ddddd"] });
    mocked.mfa.disable.mockResolvedValue();
    mocked.signOutEverywhere.mockResolvedValue();
  });

  it("enrols: shows the secret, confirms with a code, reveals recovery codes once", async () => {
    const onUserChange = vi.fn();
    render(<TwoFactorCard user={user()} onUserChange={onUserChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Set up" }));
    expect(await screen.findByText("ABCDEFGHIJKLMNOP")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open in an authenticator app/ })).toHaveAttribute(
      "href",
      expect.stringMatching(/^otpauth:\/\/totp\//),
    );
    await userEvent.type(screen.getByLabelText("Code from the app"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(mocked.mfa.confirm).toHaveBeenCalledWith("123456"));
    expect(await screen.findByText("aaaaa-bbbbb")).toBeInTheDocument();
    expect(screen.getByText(/shown only now/)).toBeInTheDocument();
    expect(onUserChange).toHaveBeenCalledWith(
      expect.objectContaining({ mfa_enabled: true, recovery_codes_left: 2 }),
    );
    await userEvent.click(screen.getByRole("button", { name: "I saved them" }));
    expect(screen.queryByText("aaaaa-bbbbb")).not.toBeInTheDocument();
  });

  it("surfaces a wrong confirmation code and stays in enrolment", async () => {
    mocked.mfa.confirm.mockRejectedValue(new Error("That code is not right; try the next one"));
    render(<TwoFactorCard user={user()} onUserChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Set up" }));
    await userEvent.type(await screen.findByLabelText("Code from the app"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not right/);
    expect(screen.getByLabelText("Code from the app")).toBeInTheDocument();
  });

  it("turns off after re-authenticating with the password", async () => {
    const onUserChange = vi.fn();
    render(
      <TwoFactorCard
        user={user({ mfa_enabled: true, recovery_codes_left: 9 })}
        onUserChange={onUserChange}
      />,
    );
    expect(screen.getByText(/9 recovery codes left/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await userEvent.type(screen.getByLabelText("Confirm with your password"), "hunter2hunter2");
    await userEvent.click(screen.getByRole("button", { name: "Turn off two-factor" }));
    await waitFor(() =>
      expect(mocked.mfa.disable).toHaveBeenCalledWith({ password: "hunter2hunter2" }),
    );
    expect(onUserChange).toHaveBeenCalledWith(expect.objectContaining({ mfa_enabled: false }));
  });

  it("asks Google-only accounts for a code instead of a password, and nudges on few codes", async () => {
    render(
      <TwoFactorCard
        user={user({ has_password: false, mfa_enabled: true, recovery_codes_left: 2 })}
        onUserChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/Few recovery codes left/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await userEvent.type(screen.getByLabelText("Confirm with a current code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Turn off two-factor" }));
    await waitFor(() => expect(mocked.mfa.disable).toHaveBeenCalledWith({ code: "654321" }));
  });

  it("signs out everywhere and says this session stays", async () => {
    render(<TwoFactorCard user={user()} onUserChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign out everywhere" }));
    await waitFor(() => expect(mocked.signOutEverywhere).toHaveBeenCalled());
    expect(await screen.findByText(/this one stays/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out everywhere" })).toBeDisabled();
  });
});
