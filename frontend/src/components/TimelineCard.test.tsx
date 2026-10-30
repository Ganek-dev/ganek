import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, applications, type TimelineEvent } from "@/lib/api";

import { TimelineCard } from "./TimelineCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    applications: { ...original.applications, timeline: vi.fn() },
  };
});

const mocked = vi.mocked(applications);
const NOW = new Date("2026-10-29T12:00:00Z");

function event(overrides: Partial<TimelineEvent>): TimelineEvent {
  return {
    id: crypto.randomUUID(),
    kind: "applied",
    at: "2026-10-29T11:00:00Z",
    actor_label: null,
    actor_email: null,
    payload: {},
    ...overrides,
  };
}

const ERIKA = { actor_label: "Erika Muster", actor_email: "erika@acme.example" };

describe("TimelineCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a skeleton, then the rows newest first with actor, copy and time", async () => {
    mocked.timeline.mockResolvedValue([
      event({ kind: "stage.changed", at: "2026-10-29T11:55:00Z", payload: { from: "new", to: "screening" }, ...ERIKA }),
      event({ kind: "email", at: "2026-10-29T11:30:00Z", payload: { template: "quiz_invite", status: "sent", attempts: 1, last_error: null } }),
      event({ kind: "quiz.completed", at: "2026-10-29T11:20:00Z", payload: { score: 0.8 } }),
      event({ kind: "quiz.started", at: "2026-10-29T11:10:00Z" }),
      event({ kind: "quiz.invited", at: "2026-10-29T10:00:00Z" }),
      event({ kind: "note.added", at: "2026-10-29T09:00:00Z", ...ERIKA }),
      event({ kind: "applied", at: "2026-10-28T12:00:00Z", payload: { source: "linkedin" } }),
    ]);
    render(<TimelineCard applicationId="a1" now={NOW} />);
    expect(screen.getByRole("region", { name: "Timeline" })).toBeInTheDocument();
    expect(document.querySelector("[aria-busy='true']")).not.toBeNull();

    const items = await screen.findAllByRole("listitem");
    expect(mocked.timeline).toHaveBeenCalledWith("a1");
    expect(items.map((li) => li.textContent)).toEqual([
      "Erika Muster moved to Screening5m ago",
      "Assessment invite email sent30m ago",
      "Quiz completed - 80%40m ago",
      "Quiz started50m ago",
      "Assessment link issued2h ago",
      "Erika Muster added a note3h ago",
      "Applied1d ago",
    ]);
  });

  it("names the candidate and the system when there is no actor", async () => {
    mocked.timeline.mockResolvedValue([
      event({ kind: "stage.changed", payload: { from: "new", to: "withdrawn" } }),
      event({ kind: "quiz.reissued", payload: { reason: "expired", mode: "auto" } }),
      event({ kind: "stage.changed", payload: { from: "new", to: "rejected", bulk: true }, actor_label: null, actor_email: "gone@acme.example" }),
      event({ kind: "quiz.expired" }),
    ]);
    render(<TimelineCard applicationId="a1" now={NOW} />);
    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Candidate withdrew");
    expect(items[1]).toHaveTextContent("System re-issued the assessment (expired)");
    expect(items[2]).toHaveTextContent("gone@acme.example moved to Rejected (bulk)");
    expect(items[3]).toHaveTextContent("Assessment link expired");
  });

  it("names the rejection reason and shows the note under the row", async () => {
    mocked.timeline.mockResolvedValue([
      event({
        kind: "stage.changed",
        payload: { from: "screening", to: "rejected", reason: "another_candidate", note: "Other finalist had the depth." },
        ...ERIKA,
      }),
    ]);
    render(<TimelineCard applicationId="a1" now={NOW} />);
    const [row] = await screen.findAllByRole("listitem");
    expect(row).toHaveTextContent("Erika Muster moved to Rejected: Another candidate preferred");
    expect(screen.getByText("Other finalist had the depth.")).toBeInTheDocument();
  });

  it("keeps 'Candidate withdrew' for a withdrawal with the withdrew reason", async () => {
    mocked.timeline.mockResolvedValue([
      event({ kind: "stage.changed", payload: { from: "new", to: "withdrawn", reason: "withdrew" } }),
    ]);
    render(<TimelineCard applicationId="a1" now={NOW} />);
    const [row] = await screen.findAllByRole("listitem");
    expect(row).toHaveTextContent("Candidate withdrew");
    expect(row).not.toHaveTextContent("Rejected");
  });

  it("explains an undelivered email under the trail", async () => {
    mocked.timeline.mockResolvedValue([
      event({ kind: "email", payload: { template: "rejection", status: "bounced", attempts: 1, last_error: null } }),
      event({ kind: "email", payload: { template: "quiz_invite", status: "queued", attempts: 2, last_error: null } }),
    ]);
    render(<TimelineCard applicationId="a1" now={NOW} />);
    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Rejection email bounced");
    expect(items[1]).toHaveTextContent("Assessment invite email retrying (attempt 2)");
    expect(screen.getByText(/bounce or a spam complaint/)).toBeInTheDocument();
  });

  it("collapses a long trail behind Show more", async () => {
    mocked.timeline.mockResolvedValue(
      Array.from({ length: 11 }, (_, i) => event({ kind: "quiz.started", id: `e${i}` })),
    );
    render(<TimelineCard applicationId="a1" now={NOW} />);
    expect(await screen.findAllByRole("listitem")).toHaveLength(8);
    await userEvent.click(screen.getByRole("button", { name: "Show 3 more" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(11);
    expect(screen.queryByRole("button", { name: /Show/ })).not.toBeInTheDocument();
  });

  it("stays quiet when the trail cannot be loaded", async () => {
    mocked.timeline.mockRejectedValue(new ApiError(500, "boom"));
    render(<TimelineCard applicationId="a1" now={NOW} />);
    expect(await screen.findByText("The timeline could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
