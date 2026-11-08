import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { billingApi, companyApi, type BillingOut, type PlanOut } from "@/lib/api";

import BillingSettingsPage from "./page";

let search = "";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/billing",
  useSearchParams: () => new URLSearchParams(search),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: { ...original.companyApi, plan: vi.fn() },
    billingApi: { get: vi.fn(), checkout: vi.fn(), portal: vi.fn() },
  };
});

const mockedCompany = vi.mocked(companyApi);
const mockedBilling = vi.mocked(billingApi);

function makePlan(over: Partial<PlanOut> = {}): PlanOut {
  return {
    plan: "free",
    billing_enabled: true,
    limits: { max_live_jobs: 1 },
    live_jobs: 1,
    over_limit: false,
    upgrade_url: "http://localhost:3000/admin/billing",
    ...over,
  };
}

function makeBilling(over: Partial<BillingOut> = {}): BillingOut {
  return { plan: "free", status: null, current_period_end: null, can_manage: false, ...over };
}

const assign = vi.fn();

describe("BillingSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search = "";
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, assign },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens Stripe Checkout for the chosen plan and interval", async () => {
    mockedCompany.plan.mockResolvedValue(makePlan());
    mockedBilling.get.mockResolvedValue(makeBilling());
    mockedBilling.checkout.mockResolvedValue({ url: "https://checkout.stripe.test/s" });
    const user = userEvent.setup();
    render(<BillingSettingsPage />);

    expect(await screen.findByTestId("billing-plan")).toHaveTextContent("Free");
    expect(screen.getByText("1 of 1 live job")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Yearly"));
    await user.click(screen.getByRole("button", { name: "Choose Team" }));

    expect(mockedBilling.checkout).toHaveBeenCalledWith("team", "year");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.stripe.test/s"));
    expect(screen.queryByRole("button", { name: "Manage billing" })).toBeNull();
  });

  it("sends a paying company to the Stripe portal", async () => {
    mockedCompany.plan.mockResolvedValue(
      makePlan({ plan: "starter", limits: { max_live_jobs: 5 }, live_jobs: 2 }),
    );
    mockedBilling.get.mockResolvedValue(
      makeBilling({
        plan: "starter",
        status: "past_due",
        current_period_end: "2026-12-08T00:00:00Z",
        can_manage: true,
      }),
    );
    mockedBilling.portal.mockResolvedValue({ url: "https://billing.stripe.test/p" });
    const user = userEvent.setup();
    render(<BillingSettingsPage />);

    expect(await screen.findByTestId("billing-plan")).toHaveTextContent("Starter");
    expect(screen.getByTestId("billing-status")).toHaveTextContent(
      "Payment failed - Stripe retries the card",
    );
    expect(screen.queryByRole("button", { name: "Choose Team" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Manage billing" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://billing.stripe.test/p"));
  });

  it("shows the Checkout error and stays on the page", async () => {
    mockedCompany.plan.mockResolvedValue(makePlan());
    mockedBilling.get.mockResolvedValue(makeBilling());
    mockedBilling.checkout.mockRejectedValue(new Error("This company already has a subscription."));
    const user = userEvent.setup();
    render(<BillingSettingsPage />);

    await user.click(await screen.findByRole("button", { name: "Choose Starter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already has a subscription");
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Choose Starter" })).toBeEnabled();
  });

  it("says billing is off when the instance has no Stripe", async () => {
    mockedCompany.plan.mockResolvedValue(makePlan({ billing_enabled: false }));
    render(<BillingSettingsPage />);
    expect(await screen.findByTestId("billing-off")).toBeInTheDocument();
    expect(mockedBilling.get).not.toHaveBeenCalled();
  });

  it("polls the plan after Checkout until the webhook upgraded it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    search = "checkout=success";
    let upgraded = false; // the webhook lands between two polls
    mockedCompany.plan.mockImplementation(async () =>
      upgraded ? makePlan({ plan: "team", limits: { max_live_jobs: null } }) : makePlan(),
    );
    mockedBilling.get.mockResolvedValue(makeBilling());
    render(<BillingSettingsPage />);

    expect(await screen.findByTestId("billing-waiting")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(screen.getByTestId("billing-plan")).toHaveTextContent("Free");
    expect(screen.getByTestId("billing-waiting")).toBeInTheDocument();
    upgraded = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(screen.getByTestId("billing-plan")).toHaveTextContent("Team");
    expect(screen.queryByTestId("billing-waiting")).toBeNull();
  });

  it("stops polling and says so when the webhook is slow", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    search = "checkout=success";
    mockedCompany.plan.mockResolvedValue(makePlan());
    mockedBilling.get.mockResolvedValue(makeBilling());
    render(<BillingSettingsPage />);

    await screen.findByTestId("billing-waiting");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000 * 15);
    });
    expect(screen.getByTestId("billing-slow")).toBeInTheDocument();
    const calls = mockedCompany.plan.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(mockedCompany.plan.mock.calls.length).toBe(calls);
  });
});
