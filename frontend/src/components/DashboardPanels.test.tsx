import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { dashboard, type StatsOverview } from "@/lib/api";

import { ActivityPanel, QueuePanel, TodayPanel } from "./DashboardPanels";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    dashboard: {
      activity: vi.fn(),
      today: vi.fn(),
      tasks: { list: vi.fn(), create: vi.fn(), toggle: vi.fn(), remove: vi.fn() },
    },
  };
});

const mocked = vi.mocked(dashboard, true);

const OVERVIEW = {
  per_job: [
    { job_id: "j1", title: "Backend Engineer", status: "published", applications: 9, new: 7 },
    { job_id: "j2", title: "SRE", status: "published", applications: 2, new: 0 },
  ],
} as unknown as StatsOverview;

describe("TodayPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders google events with meet links", async () => {
    mocked.today.mockResolvedValue({
      source: "google",
      events: [
        {
          start: "2026-08-08T11:00:00+02:00",
          summary: "Intro call — Marta Vidal",
          hangout_link: "https://meet.google.com/abc",
        },
      ],
    });
    render(<TodayPanel />);
    expect(await screen.findByText("Intro call — Marta Vidal")).toBeInTheDocument();
    expect(screen.getByText("Google Calendar")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Meet/ })).toHaveAttribute(
      "href",
      "https://meet.google.com/abc",
    );
  });

  it("suggests connecting when empty on the ganek fallback", async () => {
    mocked.today.mockResolvedValue({ source: "ganek", events: [] });
    render(<TodayPanel />);
    expect(
      await screen.findByRole("link", { name: "Connect Google Calendar" }),
    ).toHaveAttribute("href", "/admin/account");
  });
});

describe("QueuePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.tasks.list.mockResolvedValue([]);
  });

  it("derives review items from per-job new counts", async () => {
    render(<QueuePanel overview={OVERVIEW} />);
    expect(await screen.findByText("Review 7 new applicants")).toBeInTheDocument();
    expect(screen.getByText("Backend Engineer")).toBeInTheDocument();
    expect(screen.queryByText(/SRE/)).not.toBeInTheDocument(); // zero new → no item
    expect(screen.getByText("1 open")).toBeInTheDocument();
  });

  it("adds and completes manual tasks", async () => {
    mocked.tasks.create.mockResolvedValue({
      id: "t1",
      title: "Call Marta about the offer",
      note: "",
      due_date: null,
      done_at: null,
      assignee_user_id: null,
      created_by: "u1",
      created_at: "2026-08-08T10:00:00Z",
    });
    mocked.tasks.toggle.mockResolvedValue({} as never);
    render(<QueuePanel overview={null} />);
    await userEvent.type(
      await screen.findByLabelText("Add a task"),
      "Call Marta about the offer",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() =>
      expect(mocked.tasks.create).toHaveBeenCalledWith("Call Marta about the offer"),
    );
    expect(await screen.findByText("Call Marta about the offer")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Done: Call Marta about the offer"));
    await waitFor(() => expect(mocked.tasks.toggle).toHaveBeenCalledWith("t1", true));
    expect(screen.queryByText("Call Marta about the offer")).not.toBeInTheDocument();
  });
});

describe("ActivityPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("maps event types to readable copy", async () => {
    mocked.activity.mockResolvedValue([
      {
        id: "a1",
        type: "application.received",
        payload: { candidate: "Marta Vidal", job: "Backend Engineer" },
        actor_email: null,
        application_id: "app1",
        created_at: new Date(Date.now() - 60_000).toISOString(),
      },
      {
        id: "a2",
        type: "stage.changed",
        payload: { from: "new", to: "screening" },
        actor_email: "grumpy@acme.dev",
        application_id: "app1",
        created_at: new Date(Date.now() - 7_200_000).toISOString(),
      },
    ]);
    render(<ActivityPanel />);
    expect(
      await screen.findByText("Marta Vidal applied — Backend Engineer"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("grumpy@acme.dev moved a candidate new → screening"),
    ).toBeInTheDocument();
    expect(screen.getByText("just now")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
  });

  it("maps privacy event types (G2/G3) to readable copy", async () => {
    const base = {
      actor_email: "grumpy@acme.dev",
      application_id: null,
      created_at: new Date(Date.now() - 60_000).toISOString(),
    };
    mocked.activity.mockResolvedValue([
      { id: "p1", type: "candidate.erased", payload: { applications: 2 }, ...base },
      { id: "p2", type: "candidate.email_updated", payload: {}, ...base },
      { id: "p3", type: "candidate.data_requested", payload: {}, ...base, actor_email: null },
      { id: "p4", type: "candidate.deletion_requested", payload: {}, ...base, actor_email: null },
      { id: "p5", type: "user.anonymized", payload: {}, ...base },
      {
        id: "p6",
        type: "retention.purged",
        payload: { applications: 3, candidates: 2 },
        ...base,
        actor_email: null,
      },
    ]);
    render(<ActivityPanel />);
    expect(
      await screen.findByText("Candidate data erased (2 application(s))"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("grumpy@acme.dev corrected a candidate's email"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("A candidate asked for a copy of their data"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("A candidate asked for their data to be deleted"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("grumpy@acme.dev removed a teammate's account"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Retention purge removed 3 application(s)"),
    ).toBeInTheDocument();
  });
});
