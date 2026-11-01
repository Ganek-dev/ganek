import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { review, type ReviewApplicationListItem } from "@/lib/api";

import ReviewListPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, review: { list: vi.fn(), get: vi.fn() } };
});

const mocked = vi.mocked(review);

function item(over: Partial<ReviewApplicationListItem>): ReviewApplicationListItem {
  return {
    application_id: "a1",
    candidate_name: "Ada Lovelace",
    job_title: "Backend Engineer",
    stage_label: "Interview",
    scorecard_state: "open",
    scorecard_due_from: null,
    interview_start: null,
    ...over,
  };
}

describe("ReviewListPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows skeletons while loading", () => {
    mocked.list.mockReturnValue(new Promise(() => {}));
    render(<ReviewListPage />);
    expect(screen.getAllByTestId("review-skeleton").length).toBeGreaterThan(0);
  });

  it("shows the empty state", async () => {
    mocked.list.mockResolvedValue([]);
    render(<ReviewListPage />);
    expect(await screen.findByText("Nothing waiting on you.")).toBeInTheDocument();
  });

  it("renders open, submitted and interview-only status lines with links", async () => {
    mocked.list.mockResolvedValue([
      item({ application_id: "a1", candidate_name: "Ada Lovelace", scorecard_state: "open" }),
      item({ application_id: "a2", candidate_name: "Grace Hopper", scorecard_state: "submitted" }),
      item({
        application_id: "a3",
        candidate_name: "Alan Turing",
        scorecard_state: null,
        interview_start: new Date(2026, 10, 3, 10, 0).toISOString(),
      }),
    ]);
    render(<ReviewListPage />);
    expect(await screen.findByText("Scorecard due")).toBeInTheDocument();
    expect(screen.getByText("Interview 3 Nov 2026, 10:00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ada Lovelace/ })).toHaveAttribute(
      "href",
      "/review/a1",
    );
    expect(screen.getAllByText("Backend Engineer")).toHaveLength(3);
  });

  it("says Submitted without a date: the list payload has no submitted_at", async () => {
    mocked.list.mockResolvedValue([
      item({
        scorecard_state: "submitted",
        scorecard_due_from: new Date(2026, 9, 31, 12, 0).toISOString(),
      }),
      item({ application_id: "a9", candidate_name: "Linus", scorecard_state: "declined" }),
    ]);
    render(<ReviewListPage />);
    expect(await screen.findByText("Submitted")).toBeInTheDocument();
    expect(screen.queryByText(/31 Oct/)).not.toBeInTheDocument();
    expect(screen.getByText("Declined")).toBeInTheDocument();
  });

  it("shows an error when the list fails", async () => {
    mocked.list.mockRejectedValue(new Error("boom"));
    render(<ReviewListPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
  });
});
