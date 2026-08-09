import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import { AvailabilityCard } from "./AvailabilityCard";

vi.mock("@/lib/api", () => ({
  api: { availability: { get: vi.fn(), set: vi.fn() } },
}));
const mocked = vi.mocked(api.availability);

const DEFAULTS = {
  timezone: "",
  is_default: true,
  days: Object.fromEntries(
    ["mon", "tue", "wed", "thu", "fri"].map((d) => [d, { start: "09:00", end: "17:00" }]),
  ),
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.get.mockResolvedValue(DEFAULTS);
});

describe("AvailabilityCard", () => {
  it("renders seven day rows with weekend toggled off by default", async () => {
    render(<AvailabilityCard />);
    expect(await screen.findByText(/using default hours/i)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /monday/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /saturday/i })).not.toBeChecked();
  });

  it("saves the edited schedule with the browser timezone", async () => {
    mocked.set.mockResolvedValue({ ...DEFAULTS, is_default: false, timezone: "UTC" });
    render(<AvailabilityCard />);
    await screen.findByText(/using default hours/i);
    await userEvent.click(screen.getByRole("checkbox", { name: /friday/i })); // off
    await userEvent.click(screen.getByRole("button", { name: /save availability/i }));
    await waitFor(() => expect(mocked.set).toHaveBeenCalledTimes(1));
    const body = mocked.set.mock.calls[0][0];
    expect(body.days.fri).toBeUndefined();
    expect(body.days.mon).toEqual({ start: "09:00", end: "17:00" });
    expect(body.timezone).toBeTruthy(); // Intl zone of the test env
  });

  it("disables Save and warns when an enabled day's start is not before its end", async () => {
    render(<AvailabilityCard />);
    await screen.findByText(/using default hours/i);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /monday start/i }), "17:00");
    expect(await screen.findByText(/start must be before end/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save availability/i })).toBeDisabled();
    expect(mocked.set).not.toHaveBeenCalled();
  });
});
