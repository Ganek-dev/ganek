import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, interviews, team, type InterviewAdmin } from "@/lib/api";

import { InterviewCard } from "./InterviewCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    interviews: { preview: vi.fn(), create: vi.fn(), get: vi.fn(), cancel: vi.fn() },
    team: { ...original.team, list: vi.fn() },
  };
});

const mockedInterviews = vi.mocked(interviews);
const mockedTeam = vi.mocked(team);

const SLOT_A = "2027-01-05T09:00:00+00:00";
const SLOT_B = "2027-01-05T13:00:00+00:00";

function interview(overrides: Partial<InterviewAdmin> = {}): InterviewAdmin {
  return {
    id: "iv1",
    status: "pending",
    interviewer_user_id: "u1",
    interviewer_email: "dana@acme.dev",
    title: "Hiring manager interview",
    description: "",
    duration_minutes: 45,
    timezone: "Europe/Berlin",
    offered_slots: [SLOT_A, SLOT_B],
    scheduled_start: null,
    meet_url: null,
    created_at: "2026-08-08T10:00:00Z",
    ...overrides,
  };
}

describe("InterviewCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedInterviews.get.mockResolvedValue(null);
    mockedTeam.list.mockResolvedValue([
      {
        id: "u1",
        email: "dana@acme.dev",
        role: "member",
        is_active: true,
        last_login_at: null,
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "u2",
        email: "gone@acme.dev",
        role: "member",
        is_active: false,
        last_login_at: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    mockedInterviews.preview.mockResolvedValue({ slots: [SLOT_A, SLOT_B] });
    mockedInterviews.create.mockResolvedValue(interview());
    mockedInterviews.cancel.mockResolvedValue(interview({ status: "cancelled" }));
  });

  it("schedules through the modal, pruning slots", async () => {
    render(<InterviewCard applicationId="app1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Schedule interview" }));

    // inactive member is filtered from the select
    const select = await screen.findByLabelText("Interviewer");
    expect(select).toHaveValue("u1");
    expect(screen.queryByText("gone@acme.dev")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load available times" }));
    await waitFor(() =>
      expect(mockedInterviews.preview).toHaveBeenCalledWith(
        "app1",
        expect.objectContaining({ interviewer_user_id: "u1", duration_minutes: 45 }),
      ),
    );
    // prune the first slot
    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]);
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));
    await waitFor(() =>
      expect(mockedInterviews.create).toHaveBeenCalledWith(
        "app1",
        expect.objectContaining({ slots: [SLOT_B] }),
      ),
    );
    expect(await screen.findByText(/Awaiting candidate — 2 times offered/)).toBeInTheDocument();
  });

  it("explains the calendar-not-connected 409", async () => {
    mockedInterviews.preview.mockRejectedValue(
      new ApiError(409, "Interviewer has not connected Google Calendar"),
    );
    render(<InterviewCard applicationId="app1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Schedule interview" }));
    await screen.findByLabelText("Interviewer");
    await userEvent.click(screen.getByRole("button", { name: "Load available times" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Settings → Account/);
  });

  it("shows the pending state with a two-step cancel", async () => {
    mockedInterviews.get.mockResolvedValue(interview());
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByText(/Awaiting candidate/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel interview" }));
    expect(mockedInterviews.cancel).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));
    await waitFor(() => expect(mockedInterviews.cancel).toHaveBeenCalledWith("app1"));
    expect(await screen.findByRole("button", { name: "Schedule interview" })).toBeInTheDocument();
  });

  it("renders the booked state with the Meet link", async () => {
    mockedInterviews.get.mockResolvedValue(
      interview({
        status: "booked",
        scheduled_start: SLOT_B,
        meet_url: "https://meet.google.com/abc",
      }),
    );
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByText(/14:00/)).toBeInTheDocument(); // Berlin time
    expect(screen.getByRole("link", { name: /Meet/ })).toHaveAttribute(
      "href",
      "https://meet.google.com/abc",
    );
  });
});
