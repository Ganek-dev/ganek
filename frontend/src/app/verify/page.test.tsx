import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import VerifyPage from "./page";

const replace = vi.fn();
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => search,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, verifyEmail: vi.fn() },
  };
});

const mocked = vi.mocked(api);

describe("VerifyPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = new URLSearchParams({ token: "tok-1" });
    mocked.verifyEmail.mockResolvedValue({
      id: "u1",
      company_id: "c1",
      email: "a@b.dev",
      has_password: true,
      role: "admin",
    });
  });

  it("verifies the token and lands in the admin app", async () => {
    render(<VerifyPage />);
    await waitFor(() => expect(mocked.verifyEmail).toHaveBeenCalledWith({ token: "tok-1" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin"));
  });

  it("shows the expired state on a bad token", async () => {
    mocked.verifyEmail.mockRejectedValueOnce(new Error("invalid or has expired"));
    render(<VerifyPage />);
    expect(await screen.findByRole("heading", { name: /didn't work/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a new signup" })).toHaveAttribute(
      "href",
      "/setup",
    );
  });

  it("fails immediately without a token", async () => {
    search = new URLSearchParams();
    render(<VerifyPage />);
    expect(await screen.findByRole("heading", { name: /didn't work/ })).toBeInTheDocument();
    expect(mocked.verifyEmail).not.toHaveBeenCalled();
  });
});
