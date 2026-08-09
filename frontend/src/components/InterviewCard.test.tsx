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
    scheduled_start: null,
    meet_url: null,
    created_at: "2026-08-08T10:00:00Z",
    ...overrides,
  };
}

async function openDialog() {
  render(<InterviewCard applicationId="app1" />);
  await userEvent.click(await screen.findByRole("button", { name: "Schedule interview" }));
  await screen.findByLabelText("Interviewer");
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
    mockedInterviews.preview.mockResolvedValue({
      schedule_summary: "Mon–Fri 09:00–17:00",
      open_slot_count: 23,
    });
    mockedInterviews.create.mockResolvedValue(interview());
    mockedInterviews.cancel.mockResolvedValue(interview({ status: "cancelled" }));
  });

  it("shows the availability summary once an interviewer is picked", async () => {
    mockedInterviews.preview.mockResolvedValue({
      schedule_summary: "Mon–Fri 09:00–17:00",
      open_slot_count: 23,
    });
    await openDialog();

    // inactive member is filtered from the select
    const select = screen.getByLabelText("Interviewer");
    expect(select).toHaveValue("u1");
    expect(screen.queryByText("gone@acme.dev")).not.toBeInTheDocument();

    expect(await screen.findByText(/Mon–Fri 09:00–17:00.*23 open times/i)).toBeInTheDocument();
    expect(mockedInterviews.preview).toHaveBeenCalledWith(
      "app1",
      expect.objectContaining({ interviewer_user_id: "u1", duration_minutes: 45 }),
    );
  });

  it("disables Send when there are no open times", async () => {
    mockedInterviews.preview.mockResolvedValue({
      schedule_summary: "Mon–Fri 09:00–17:00",
      open_slot_count: 0,
    });
    await openDialog();

    expect(await screen.findByRole("button", { name: /send invite/i })).toBeDisabled();
    expect(screen.getByText(/no open times/i)).toBeInTheDocument();
  });

  it("sends without a slots payload", async () => {
    await openDialog();
    await screen.findByText(/23 open times/i);

    await userEvent.click(screen.getByRole("button", { name: /send invite/i }));
    await waitFor(() =>
      expect(mockedInterviews.create).toHaveBeenCalledWith(
        "app1",
        expect.not.objectContaining({ slots: expect.anything() }),
      ),
    );
    expect(mockedInterviews.create).toHaveBeenCalledWith(
      "app1",
      expect.objectContaining({ interviewer_user_id: "u1", duration_minutes: 45 }),
    );
  });

  it("explains the calendar-not-connected error", async () => {
    mockedInterviews.preview.mockRejectedValue(
      new ApiError(409, "Interviewer has not connected Google Calendar"),
    );
    await openDialog();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Settings → Account/);
  });

  it("shows availability-based pending copy", async () => {
    mockedInterviews.get.mockResolvedValue(interview());
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByText(/uses .*availability/i)).toBeInTheDocument();
    expect(screen.getByText(/dana@acme\.dev/)).toBeInTheDocument();
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
