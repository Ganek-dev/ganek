import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { shortTime } from "@/lib/time";

import { ImpersonationBanner } from "./ImpersonationBanner";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: { ...original.api, endImpersonation: vi.fn() } };
});

const mocked = vi.mocked(api);
const reload = vi.fn();

describe("ImpersonationBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("location", { ...window.location, reload });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("says who is being viewed, until when, and that it is read-only", () => {
    const expiresAt = new Date(Date.now() + 30 * 60_000).toISOString();
    render(<ImpersonationBanner email="grumpy@acme.dev" expiresAt={expiresAt} />);
    const banner = screen.getByTestId("impersonation-banner");
    expect(banner).toHaveTextContent("Viewing as grumpy@acme.dev.");
    expect(banner).toHaveTextContent(`read-only, ends at ${shortTime(expiresAt)}`);
  });

  it("ends the impersonation and reloads into the operator's own account", async () => {
    mocked.endImpersonation.mockResolvedValue(undefined);
    render(
      <ImpersonationBanner
        email="grumpy@acme.dev"
        expiresAt={new Date(Date.now() + 60_000).toISOString()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "End impersonation" }));
    expect(mocked.endImpersonation).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it("keeps the button and says so when ending fails", async () => {
    mocked.endImpersonation.mockRejectedValue(new Error("down"));
    render(
      <ImpersonationBanner
        email="grumpy@acme.dev"
        expiresAt={new Date(Date.now() + 60_000).toISOString()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "End impersonation" }));
    expect(await screen.findByText(/Couldn't end it, try again/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End impersonation" })).toBeEnabled();
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads the page once the hour is up", () => {
    vi.useFakeTimers();
    render(
      <ImpersonationBanner
        email="grumpy@acme.dev"
        expiresAt={new Date(Date.now() + 5_000).toISOString()}
      />,
    );
    vi.advanceTimersByTime(5_500);
    expect(reload).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1_000);
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
