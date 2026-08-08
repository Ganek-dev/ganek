import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, publicInterviews, type InterviewPublic } from "@/lib/api";

import InterviewBookingPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "iv-tok" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    publicInterviews: {
      get: vi.fn(),
      book: vi.fn(),
      reschedule: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

const mocked = vi.mocked(publicInterviews);

const SLOT_A = "2027-01-05T09:00:00+00:00"; // Tue 10:00 Berlin
const SLOT_B = "2027-01-05T13:00:00+00:00"; // Tue 14:00 Berlin
const SLOT_C = "2027-01-06T10:30:00+00:00"; // Wed 11:30 Berlin

function interview(overrides: Partial<InterviewPublic> = {}): InterviewPublic {
  return {
    company_name: "Northwind Robotics",
    brand_primary: "#3b82f6",
    logo_url: null,
    job_title: "Backend Engineer",
    candidate_first_name: "Marta",
    title: "Hiring manager interview",
    description: "Your work, our stack, and the first 90 days.",
    duration_minutes: 45,
    timezone: "Europe/Berlin",
    status: "pending",
    interviewer_display: "Dana Kowalska",
    available_slots: [SLOT_A, SLOT_B, SLOT_C],
    scheduled_start: null,
    meet_url: null,
    ...overrides,
  };
}

describe("InterviewBookingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(interview());
  });

  it("renders the pending state with interviewer panel and slot grid", async () => {
    render(<InterviewBookingPage />);
    expect(await screen.findByRole("heading", { name: "Pick a time, Marta" })).toBeInTheDocument();
    expect(screen.getByText("Dana Kowalska")).toBeInTheDocument();
    expect(screen.getByText("45 minutes")).toBeInTheDocument();
    expect(screen.getByText(/Europe\/Berlin/)).toBeInTheDocument();
    // Berlin renders 09:00 UTC as 10:00
    expect(screen.getByRole("button", { name: "10:00" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "14:00" })).toBeInTheDocument();
  });

  it("books the selected slot", async () => {
    mocked.book.mockResolvedValue(
      interview({ status: "booked", scheduled_start: SLOT_B, meet_url: "https://meet.g/x" }),
    );
    render(<InterviewBookingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "14:00" }));
    expect(screen.getByText(/14:00–14:45/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm interview" }));
    await waitFor(() => expect(mocked.book).toHaveBeenCalledWith("iv-tok", SLOT_B));
    expect(await screen.findByRole("heading", { name: "You're booked in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Meet link" })).toHaveAttribute(
      "href",
      "https://meet.g/x",
    );
  });

  it("recovers when the slot was just taken", async () => {
    mocked.book.mockRejectedValueOnce(new ApiError(409, "slot-taken"));
    render(<InterviewBookingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "10:00" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm interview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/just taken/i);
    await waitFor(() => expect(mocked.get).toHaveBeenCalledTimes(2)); // refetched
  });

  it("reschedules from the booked state", async () => {
    mocked.get.mockResolvedValue(
      interview({ status: "booked", scheduled_start: SLOT_A, meet_url: "https://meet.g/x" }),
    );
    mocked.reschedule.mockResolvedValue(
      interview({ status: "booked", scheduled_start: SLOT_C, meet_url: "https://meet.g/x" }),
    );
    render(<InterviewBookingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reschedule" }));
    await userEvent.click(screen.getByRole("button", { name: "11:30" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm new time" }));
    await waitFor(() => expect(mocked.reschedule).toHaveBeenCalledWith("iv-tok", SLOT_C));
  });

  it("cancels only after the two-step confirm", async () => {
    mocked.get.mockResolvedValue(interview({ status: "booked", scheduled_start: SLOT_A }));
    mocked.cancel.mockResolvedValue(interview({ status: "cancelled" }));
    render(<InterviewBookingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel interview" }));
    expect(mocked.cancel).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));
    await waitFor(() => expect(mocked.cancel).toHaveBeenCalledWith("iv-tok"));
    expect(
      await screen.findByRole("heading", { name: "This interview was cancelled" }),
    ).toBeInTheDocument();
  });

  it("renders the cancelled state", async () => {
    mocked.get.mockResolvedValue(interview({ status: "cancelled", available_slots: [] }));
    render(<InterviewBookingPage />);
    expect(
      await screen.findByRole("heading", { name: "This interview was cancelled" }),
    ).toBeInTheDocument();
  });

  it("renders the invalid state on 404", async () => {
    mocked.get.mockRejectedValue(new ApiError(404, "Interview not found"));
    render(<InterviewBookingPage />);
    expect(
      await screen.findByRole("heading", { name: /isn't valid anymore/ }),
    ).toBeInTheDocument();
  });
});
