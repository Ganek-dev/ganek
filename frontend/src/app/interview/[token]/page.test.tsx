// Pin the test-runner timezone so day-strip grouping / time labels are
// deterministic regardless of the machine or CI runner's default TZ (the
// component derives its display zone from Intl.DateTimeFormat().resolvedOptions()
// at render time, which reads process.env.TZ under Node). No other test in
// this file's worker asserts a specific local-hour value, so this is safe
// to set unconditionally before any imports run.
process.env.TZ = "Europe/Berlin";

import { act, render, screen, waitFor } from "@testing-library/react";
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

// A Monday with 3 open slots and a Tuesday with 2, for day-strip grouping.
const MON_1 = "2026-08-10T08:00:00+00:00"; // Mon 10:00 Berlin
const MON_2 = "2026-08-10T09:00:00+00:00"; // Mon 11:00 Berlin
const MON_3 = "2026-08-10T10:00:00+00:00"; // Mon 12:00 Berlin
const TUE_1 = "2026-08-11T08:00:00+00:00"; // Tue 10:00 Berlin
const TUE_2 = "2026-08-11T09:00:00+00:00"; // Tue 11:00 Berlin

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

function withSlots(slots: string[]): InterviewPublic {
  return interview({ available_slots: slots });
}

/** A promise plus its own resolver, so a test can control exactly when a
 * mocked request settles — needed to reproduce request races (a stale
 * re-check GET resolving after a newer book/reschedule/cancel response). */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("InterviewBookingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(interview());
  });

  it("renders the pending state with interviewer panel and a day-strip time list", async () => {
    render(<InterviewBookingPage />);
    expect(await screen.findByRole("heading", { name: "Pick a time, Marta" })).toBeInTheDocument();
    expect(screen.getByText("Dana Kowalska")).toBeInTheDocument();
    expect(screen.getByText("45 minutes")).toBeInTheDocument();
    expect(screen.getByText(/Europe\/Berlin/)).toBeInTheDocument();
    // first day (Tue, holding SLOT_A + SLOT_B) is auto-selected
    const tueTab = screen.getByRole("tab", { name: /tue.*2/i });
    expect(tueTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /wed.*1/i })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("button", { name: "10:00" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "14:00" })).toBeInTheDocument();
    // Wed's slot isn't shown until its day chip is active
    expect(screen.queryByRole("button", { name: "11:30" })).not.toBeInTheDocument();
  });

  it("groups slots into a day strip in the visitor's timezone and books from the time list", async () => {
    mocked.get.mockResolvedValue(withSlots([MON_1, MON_2, MON_3, TUE_1, TUE_2]));
    mocked.book.mockResolvedValue(
      interview({ status: "booked", scheduled_start: MON_1, meet_url: "https://meet.g/x" }),
    );
    render(<InterviewBookingPage />);
    const mondayTab = await screen.findByRole("tab", { name: /mon.*3/i });
    expect(mondayTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /tue.*2/i })).toHaveAttribute("aria-selected", "false");
    await userEvent.click(mondayTab);
    await userEvent.click(screen.getByRole("button", { name: "10:00" }));
    await userEvent.click(screen.getByRole("button", { name: /confirm interview/i }));
    expect(mocked.book).toHaveBeenCalledWith("iv-tok", MON_1);
  });

  it("renders every day with slots, even past the old 14-day cap", async () => {
    // 15 distinct interviewer-tz days, one slot each — the day strip used to
    // slice to MAX_DAY_CHIPS (14), silently dropping the 15th.
    const fifteenDays = Array.from(
      { length: 15 },
      (_, i) => `2026-08-${String(10 + i).padStart(2, "0")}T08:00:00+00:00`,
    );
    mocked.get.mockResolvedValue(withSlots(fifteenDays));
    render(<InterviewBookingPage />);
    await screen.findByRole("tablist");
    expect(screen.getAllByRole("tab")).toHaveLength(15);
  });

  it("shows the local-timezone pill", async () => {
    render(<InterviewBookingPage />);
    expect(await screen.findByText(/your local time/i)).toBeInTheDocument();
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

  it("recovers when the slot was just taken at confirm time", async () => {
    mocked.book.mockRejectedValueOnce(new ApiError(409, "slot-taken"));
    render(<InterviewBookingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "10:00" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm interview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/just taken/i);
    // initial load + select re-check + post-conflict reload
    await waitFor(() => expect(mocked.get).toHaveBeenCalledTimes(3));
  });

  it("re-checks on select and greys a just-taken slot", async () => {
    mocked.get
      .mockResolvedValueOnce(withSlots(["2026-08-12T08:00:00Z", "2026-08-12T09:00:00Z"]))
      .mockResolvedValueOnce(withSlots(["2026-08-12T09:00:00Z"]));
    render(<InterviewBookingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "10:00" })); // 08:00Z in Berlin (CEST)
    expect(await screen.findByText(/just taken/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm interview/i })).not.toBeInTheDocument();
  });

  it("keeps the booked state when a stale re-check GET resolves after booking succeeds", async () => {
    const staleGet = deferred<InterviewPublic>();
    mocked.get
      .mockResolvedValueOnce(interview()) // initial mount load
      .mockImplementationOnce(() => staleGet.promise); // re-check GET from selecting the slot — left pending
    mocked.book.mockResolvedValue(
      interview({ status: "booked", scheduled_start: SLOT_A, meet_url: "https://meet.g/x" }),
    );
    render(<InterviewBookingPage />);
    // clicking the slot fires the (still-pending) re-check GET, then confirm
    // races ahead of it and books successfully.
    await userEvent.click(await screen.findByRole("button", { name: "10:00" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm interview" }));
    expect(await screen.findByRole("heading", { name: "You're booked in" })).toBeInTheDocument();

    // the stale re-check GET — started before booking — resolves last, with
    // a pre-booking snapshot. It must not be allowed to revert the UI.
    await act(async () => {
      staleGet.resolve(interview());
      await staleGet.promise;
    });
    expect(screen.getByRole("heading", { name: "You're booked in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /pick a time/i })).not.toBeInTheDocument();
  });

  it("disables the day strip while a booking write is in flight", async () => {
    const bookDeferred = deferred<InterviewPublic>();
    mocked.book.mockImplementationOnce(() => bookDeferred.promise);
    render(<InterviewBookingPage />);

    await userEvent.click(await screen.findByRole("button", { name: "10:00" })); // select SLOT_A
    const getCallsBeforeConfirm = mocked.get.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Confirm interview" })); // book() now in flight

    // While the book POST is in flight, day-tab and time-pill controls must
    // be disabled — a fresh selection here would bump requestSeq past this
    // write's, causing its own (about-to-land) response to be discarded.
    const otherTime = screen.getByRole("button", { name: "14:00" });
    const otherDay = screen.getByRole("tab", { name: /wed/i });
    expect(otherTime).toBeDisabled();
    expect(otherDay).toBeDisabled();
    await userEvent.click(otherTime);
    await userEvent.click(otherDay);
    expect(mocked.get).toHaveBeenCalledTimes(getCallsBeforeConfirm); // no new re-check GET fired
    expect(screen.getByRole("button", { name: "10:00" })).toHaveAttribute("aria-pressed", "true");
    expect(otherDay).toHaveAttribute("aria-selected", "false"); // active day unchanged

    // the in-flight booking still lands normally once it resolves
    await act(async () => {
      bookDeferred.resolve(
        interview({ status: "booked", scheduled_start: SLOT_A, meet_url: "https://meet.g/x" }),
      );
      await bookDeferred.promise;
    });
    expect(await screen.findByRole("heading", { name: "You're booked in" })).toBeInTheDocument();
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
    await userEvent.click(await screen.findByRole("tab", { name: /wed/i }));
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
