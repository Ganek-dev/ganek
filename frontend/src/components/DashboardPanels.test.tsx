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
      queue: { list: vi.fn(), dismiss: vi.fn() },
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

  it("renders booked interviews with their location", async () => {
    mocked.today.mockResolvedValue({
      events: [
        {
          start: "2026-08-08T11:00:00+02:00",
          summary: "Intro call - Marta Vidal",
          location: "https://teams.example/room-2",
        },
        { start: "2026-08-08T14:00:00+02:00", summary: "Panel - Jonas Weber", location: "Room 2" },
      ],
    });
    render(<TodayPanel />);
    expect(await screen.findByText("Intro call - Marta Vidal")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /teams\.example/ })).toHaveAttribute(
      "href",
      "https://teams.example/room-2",
    );
    expect(screen.getByText("Room 2")).toBeInTheDocument();
    expect(screen.queryByText(/Google/)).not.toBeInTheDocument();
  });

  it("says so when nothing is scheduled, without any connect prompt", async () => {
    mocked.today.mockResolvedValue({ events: [] });
    render(<TodayPanel />);
    expect(await screen.findByText("Nothing scheduled today.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Connect/ })).not.toBeInTheDocument();
  });
});

const QUEUE_ITEMS = [
  {
    key: "job-quiz:j2",
    kind: "job-quiz" as const,
    title: "Add a quiz to SRE",
    hint: "Published without screening",
    href: "/admin/jobs/j2",
    since: null,
  },
  {
    key: "integrity:a1",
    kind: "integrity" as const,
    title: "Review quiz flags: Marta Vidal",
    hint: "SRE · left the tab 3x (~40s)",
    href: "/admin/applicants?selected=app1",
    since: "2026-10-21T08:00:00Z",
  },
  {
    key: "unbooked:i1",
    kind: "unbooked" as const,
    title: "Awaiting booking: Tomas Hruby",
    hint: "SRE · Hiring manager interview",
    href: "/admin/applicants?selected=app2",
    since: "2026-10-20T08:00:00Z",
  },
];

describe("QueuePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.tasks.list.mockResolvedValue([]);
    mocked.queue.list.mockResolvedValue({ items: [] });
  });

  it("lists the backend's derived items with links into the admin screens", async () => {
    mocked.queue.list.mockResolvedValue({ items: QUEUE_ITEMS });
    render(<QueuePanel overview={OVERVIEW} />);
    expect(await screen.findByText("Add a quiz to SRE")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add a quiz to SRE/ })).toHaveAttribute(
      "href",
      "/admin/jobs/j2",
    );
    expect(screen.getByRole("link", { name: /Review quiz flags: Marta Vidal/ })).toHaveAttribute(
      "href",
      "/admin/applicants?selected=app1",
    );
    expect(screen.getByRole("link", { name: /Awaiting booking: Tomas Hruby/ })).toHaveAttribute(
      "href",
      "/admin/applicants?selected=app2",
    );
    // 1 new-applicants item + 3 derived
    expect(screen.getByText("4 open")).toBeInTheDocument();
  });

  it("dismisses a derived item optimistically and tells the backend", async () => {
    mocked.queue.list.mockResolvedValue({ items: QUEUE_ITEMS });
    mocked.queue.dismiss.mockResolvedValue(undefined);
    render(<QueuePanel overview={OVERVIEW} />);
    await screen.findByText("Add a quiz to SRE");
    await userEvent.click(screen.getByRole("button", { name: "Dismiss: Add a quiz to SRE" }));
    expect(screen.queryByText("Add a quiz to SRE")).not.toBeInTheDocument();
    expect(mocked.queue.dismiss).toHaveBeenCalledWith("job-quiz:j2");
    expect(screen.getByText("3 open")).toBeInTheDocument();
  });

  it("reloads the queue when a dismissal fails", async () => {
    mocked.queue.list.mockResolvedValue({ items: [QUEUE_ITEMS[0]] });
    mocked.queue.dismiss.mockRejectedValue(new Error("boom"));
    render(<QueuePanel overview={OVERVIEW} />);
    await screen.findByText("Add a quiz to SRE");
    await userEvent.click(screen.getByRole("button", { name: "Dismiss: Add a quiz to SRE" }));
    await waitFor(() => expect(mocked.queue.list).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Add a quiz to SRE")).toBeInTheDocument();
  });

  it("keeps the panel usable when the queue request fails", async () => {
    mocked.queue.list.mockRejectedValue(new Error("offline"));
    render(<QueuePanel overview={OVERVIEW} />);
    expect(await screen.findByText("Review 7 new applicants")).toBeInTheDocument();
    expect(screen.getByText("1 open")).toBeInTheDocument();
  });

  it("derives review items from per-job new counts", async () => {
    render(<QueuePanel overview={OVERVIEW} />);
    expect(await screen.findByText("Review 7 new applicants")).toBeInTheDocument();
    expect(screen.getByText("Backend Engineer")).toBeInTheDocument();
    expect(screen.queryByText(/SRE/)).not.toBeInTheDocument(); // zero new -> no item
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
      await screen.findByText("Marta Vidal applied - Backend Engineer"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("grumpy@acme.dev moved a candidate from new to screening"),
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

describe("QueuePanel scorecard items", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.tasks.list.mockResolvedValue([]);
  });

  it("shows a clipboard icon for a scorecard and an hourglass for a waiting one", async () => {
    mocked.queue.list.mockResolvedValue({
      items: [
        {
          key: "scorecard:s1",
          kind: "scorecard" as const,
          title: "Score Marta Vidal",
          hint: "SRE",
          href: "/review/app1",
          since: null,
        },
        {
          key: "scorecard-waiting:s2",
          kind: "scorecard-waiting" as const,
          title: "Waiting on Jonas Weber",
          hint: "SRE",
          href: "/admin/applicants?selected=app2",
          since: null,
        },
        {
          key: "job-quiz:j2",
          kind: "job-quiz" as const,
          title: "Add a quiz to SRE",
          hint: "Published without screening",
          href: "/admin/jobs/j2",
          since: null,
        },
      ],
    });
    render(<QueuePanel overview={null} />);
    await screen.findByText("Score Marta Vidal");
    expect(screen.getByTestId("queue-icon-scorecard")).toBeInTheDocument();
    expect(screen.getByTestId("queue-icon-scorecard-waiting")).toBeInTheDocument();
    // existing kinds keep their rendering: no icon element
    const quizRow = screen.getByRole("link", { name: /Add a quiz to SRE/ }).closest("li");
    expect(quizRow?.querySelector("[data-testid]")).toBeNull();
  });
});

describe("QueuePanel stalled role item", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.tasks.list.mockResolvedValue([]);
  });

  it("renders a stalled role item with its icon and link", async () => {
    mocked.queue.list.mockResolvedValue({
      items: [
        {
          key: "role-stalled:j9",
          kind: "role-stalled" as const,
          title: "Backend Engineer: no movement for 9 days",
          hint: "3 waiting on you",
          href: "/admin/applicants?job=j9",
          since: null,
        },
      ],
    });
    render(<QueuePanel overview={null} />);
    await screen.findByText("Backend Engineer: no movement for 9 days");
    expect(screen.getByText("3 waiting on you")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Backend Engineer: no movement for 9 days/ }),
    ).toHaveAttribute("href", "/admin/applicants?job=j9");
    expect(screen.getByTestId("queue-icon-role-stalled")).toBeInTheDocument();
  });
});
