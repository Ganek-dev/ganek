import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BoardJob, BoardOut } from "@/lib/api";

import { OpenRolesBoard } from "./OpenRolesBoard";

function job(over: Partial<BoardJob>): BoardJob {
  return {
    job_id: "j1",
    title: "Backend Engineer",
    job_status: "published",
    status: "stalled",
    live_by_stage: { new: 1, screening: 3, interview: 1, offer: 0 },
    waiting_on_team: 3,
    longest_wait_days: 11,
    overdue: 3,
    new_7d: 0,
    moved_7d: 0,
    days_open: 34,
    last_movement_at: null,
    reason: "No candidate moved in the last 7 days. 3 waiting on you.",
    ...over,
  };
}

function board(jobs: BoardJob[]): BoardOut {
  return {
    stage_limit_days: 7,
    totals: { active_jobs: jobs.length, live: 0, waiting_on_team: 0, overdue: 0, new_7d: 0 },
    jobs,
  };
}

const JOBS = [
  job({}),
  job({
    job_id: "j2",
    title: "Product Designer",
    job_status: "closed",
    status: "on_track",
    waiting_on_team: 0,
    longest_wait_days: null,
    overdue: 0,
    days_open: 60,
    reason: "Moving along.",
  }),
  job({ job_id: "j3", title: "SRE", status: "attention", overdue: 2, reason: "Two wait." }),
];

describe("OpenRolesBoard", () => {
  it("renders one row per job in the given order with the closed tag", () => {
    render(<OpenRolesBoard board={board(JOBS)} />);
    const table = screen.getByRole("table", { name: "Open roles" });
    const rows = within(table).getAllByRole("row").slice(2); // two header rows
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/admin/applicants?job=j1",
    );
    expect(within(rows[1]).getByRole("link", { name: "Product Designer" })).toBeInTheDocument();
    expect(within(rows[2]).getByRole("link", { name: "SRE" })).toBeInTheDocument();
    expect(within(rows[1]).getByText("Closed")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("Closed")).toBeNull();
    expect(within(rows[0]).getByText("34 d")).toBeInTheDocument();
    expect(within(rows[1]).getByText("60 d, closed")).toBeInTheDocument();
    expect(within(rows[0]).getByText("longest 11 d")).toBeInTheDocument();
  });

  it("shows the rule sentence under the title and as the chip title", () => {
    render(<OpenRolesBoard board={board([JOBS[0]])} />);
    const table = screen.getByRole("table", { name: "Open roles" });
    const sentence = within(table).getByText(JOBS[0].reason);
    expect(sentence.tagName).toBe("P");
    expect(within(table).getByText("Stalled").closest("span[title]")).toHaveAttribute(
      "title",
      JOBS[0].reason,
    );
  });

  it("links the waiting-on-you cell to the waiting filter", () => {
    render(<OpenRolesBoard board={board([JOBS[0]])} />);
    const table = screen.getByRole("table", { name: "Open roles" });
    const link = within(table).getByRole("link", { name: "3 waiting on you, longest 11 days" });
    expect(link).toHaveAttribute("href", "/admin/applicants?job=j1&waiting=team");
  });

  it("keeps the overdue cell as plain text, warn coloured above zero", () => {
    render(<OpenRolesBoard board={board([JOBS[0], JOBS[1]])} />);
    const table = screen.getByRole("table", { name: "Open roles" });
    const rows = within(table).getAllByRole("row").slice(2);
    const overdue = within(rows[0]).getByTestId("overdue-j1");
    expect(overdue).toHaveTextContent("3");
    expect(overdue.closest("a")).toBeNull();
    expect(overdue.className).toContain("text-warn");
    const zero = within(rows[1]).getByTestId("overdue-j2");
    expect(zero.className).not.toContain("text-warn");
  });

  it("renders a card per role with the same facts below lg", () => {
    render(<OpenRolesBoard board={board([JOBS[0]])} />);
    const list = screen.getByRole("list", { name: "Open roles" });
    const card = within(list).getByRole("listitem");
    expect(within(card).getByRole("link", { name: "Backend Engineer" })).toBeInTheDocument();
    expect(within(card).getByText(JOBS[0].reason)).toBeInTheDocument();
    expect(within(card).getByText("Stalled")).toBeInTheDocument();
    expect(within(card).getByText("open 34 d")).toBeInTheDocument();
  });

  it("links the card waiting fact to the waiting filter", () => {
    render(<OpenRolesBoard board={board([JOBS[0], JOBS[1]])} />);
    const cards = within(screen.getByRole("list", { name: "Open roles" })).getAllByRole("listitem");
    expect(
      within(cards[0]).getByRole("link", { name: "3 waiting on you, longest 11 days" }),
    ).toHaveAttribute("href", "/admin/applicants?job=j1&waiting=team");
    expect(within(cards[1]).queryByRole("link", { name: /waiting on you/ })).toBeNull();
  });

  it("scrolls the table horizontally instead of overflowing the card", () => {
    render(<OpenRolesBoard board={board([JOBS[0]])} />);
    const table = screen.getByRole("table", { name: "Open roles" });
    expect(table.parentElement?.className).toContain("overflow-x-auto");
  });

  it("shows the empty state", () => {
    render(<OpenRolesBoard board={board([])} />);
    expect(screen.getByText("Publish a job to see its pipeline here.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
