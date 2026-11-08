import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, interviews, team, type InterviewAdmin } from "@/lib/api";

import { InterviewCard, nextRound } from "./InterviewCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    interviews: { preview: vi.fn(), create: vi.fn(), get: vi.fn(), list: vi.fn(), cancel: vi.fn() },
    team: { ...original.team, list: vi.fn() },
  };
});

const mockedInterviews = vi.mocked(interviews);
const mockedTeam = vi.mocked(team);

const SLOT_B = "2027-01-05T13:00:00+00:00";

function interview(overrides: Partial<InterviewAdmin> = {}): InterviewAdmin {
  return {
    id: "iv1",
    round_number: 1,
    status: "pending",
    completed: false,
    interviewer_user_id: "u1",
    interviewer_email: "dana@acme.dev",
    title: "Hiring manager interview",
    description: "",
    duration_minutes: 45,
    timezone: "Europe/Berlin",
    scheduled_start: null,
    location: "",
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
    mockedInterviews.list.mockResolvedValue([]);
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
      schedule_summary: "Mon-Fri 09:00-17:00",
      open_slot_count: 23,
      default_location: "",
    });
    mockedInterviews.create.mockResolvedValue(interview());
    mockedInterviews.cancel.mockResolvedValue(interview({ status: "cancelled" }));
  });

  it("shows the availability summary once an interviewer is picked", async () => {
    mockedInterviews.preview.mockResolvedValue({
      schedule_summary: "Mon-Fri 09:00-17:00",
      open_slot_count: 23,
      default_location: "",
    });
    await openDialog();

    // inactive member is filtered from the select
    const select = screen.getByLabelText("Interviewer");
    expect(select).toHaveValue("u1");
    expect(screen.queryByText("gone@acme.dev")).not.toBeInTheDocument();

    expect(await screen.findByText(/Mon-Fri 09:00-17:00.*23 open times/i)).toBeInTheDocument();
    expect(mockedInterviews.preview).toHaveBeenCalledWith(
      "app1",
      expect.objectContaining({ interviewer_user_id: "u1", duration_minutes: 45 }),
    );
  });

  it("disables Send when there are no open times", async () => {
    mockedInterviews.preview.mockResolvedValue({
      schedule_summary: "Mon-Fri 09:00-17:00",
      open_slot_count: 0,
      default_location: "",
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

  it("prefills the location from the interviewer default and sends it", async () => {
    mockedInterviews.preview.mockResolvedValue({
      schedule_summary: "Mon-Fri 09:00-17:00",
      open_slot_count: 23,
      default_location: "Room 2",
    });
    await openDialog();
    const where = await screen.findByLabelText("Where");
    await waitFor(() => expect(where).toHaveValue("Room 2"));
    await userEvent.clear(where);
    await userEvent.type(where, "https://zoom.example/j/1");
    await userEvent.click(screen.getByRole("button", { name: /send invite/i }));
    await waitFor(() =>
      expect(mockedInterviews.create).toHaveBeenCalledWith(
        "app1",
        expect.objectContaining({ location: "https://zoom.example/j/1" }),
      ),
    );
  });

  it("says both sides get a calendar invite and never mentions Google", async () => {
    await openDialog();
    expect(screen.getByText(/both of you get a calendar invite/i)).toBeInTheDocument();
    expect(screen.queryByText(/Google/)).not.toBeInTheDocument();
  });

  it("surfaces a preview error as-is", async () => {
    mockedInterviews.preview.mockRejectedValue(new ApiError(422, "Unknown timezone"));
    await openDialog();
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown timezone");
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

  it("shows the location as a link when it is a URL", async () => {
    mockedInterviews.get.mockResolvedValue(
      interview({
        status: "booked",
        scheduled_start: SLOT_B,
        location: "https://teams.example/room-2",
      }),
    );
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByText(/14:00/)).toBeInTheDocument(); // Berlin time
    expect(screen.getByRole("link", { name: /teams\.example/ })).toHaveAttribute(
      "href",
      "https://teams.example/room-2",
    );
  });

  it("shows the location as text otherwise", async () => {
    mockedInterviews.get.mockResolvedValue(
      interview({ status: "booked", scheduled_start: SLOT_B, location: "Room 2, 3rd floor" }),
    );
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByText("Room 2, 3rd floor")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Room 2/ })).not.toBeInTheDocument();
  });

  it("offers the next round once the previous one is over", async () => {
    mockedInterviews.list.mockResolvedValue([
      interview({
        id: "iv0",
        status: "booked",
        completed: true,
        scheduled_start: "2026-08-10T08:00:00Z",
      }),
    ]);
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByRole("button", { name: "Schedule round 2" })).toBeInTheDocument();
    expect(screen.getByText("Interview · round 2")).toBeInTheDocument();
    const earlier = screen.getByRole("list", { name: "Earlier rounds" });
    expect(earlier).toHaveTextContent("Round 1");
    expect(earlier).toHaveTextContent("Done");
  });

  it("shows the active round number next to earlier rounds", async () => {
    mockedInterviews.get.mockResolvedValue(interview({ id: "iv2", round_number: 2 }));
    mockedInterviews.list.mockResolvedValue([
      interview({ id: "iv0", status: "booked", completed: true, scheduled_start: SLOT_B }),
      interview({ id: "iv1", round_number: 2, status: "cancelled" }),
      interview({ id: "iv2", round_number: 2 }),
    ]);
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByText("Interview · round 2")).toBeInTheDocument();
    expect(screen.getByText(/Awaiting candidate/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Schedule/ })).toBeNull();
    // only finished rounds are history; the cancelled request is not
    await waitFor(() =>
      expect(screen.getByRole("list", { name: "Earlier rounds" }).children).toHaveLength(1),
    );
  });

  it("keeps the first round labelled plainly when the history fails to load", async () => {
    mockedInterviews.list.mockRejectedValue(new ApiError(500, "boom"));
    render(<InterviewCard applicationId="app1" />);
    expect(await screen.findByRole("button", { name: "Schedule interview" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Earlier rounds" })).toBeNull();
  });

  it("numbers the next round past the highest finished one", () => {
    expect(nextRound([])).toBe(1);
    expect(nextRound([interview({ round_number: 1 }), interview({ round_number: 3 })])).toBe(4);
  });
});
