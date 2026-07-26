import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { publicApplications, type ApplicationStatus } from "@/lib/api";

import StatusPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "status-tok" }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    publicApplications: { status: vi.fn(), withdraw: vi.fn() },
  };
});

const mocked = vi.mocked(publicApplications);

function makeStatus(overrides: Partial<ApplicationStatus> = {}): ApplicationStatus {
  return {
    company_name: "Northwind Robotics",
    brand_primary: "#3d5afe",
    job_title: "Senior Frontend Engineer",
    candidate_name: "Marta Vidal",
    cv_filename: "marta-vidal-cv.pdf",
    applied_at: "2026-07-24T14:58:00Z",
    stage: "screening",
    quiz: {
      status: "completed",
      answered: 12,
      total: 12,
      completed_at: "2026-07-24T15:12:00Z",
    },
    decision_expected_by: "2026-08-07T14:58:00Z",
    ...overrides,
  };
}

describe("StatusPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.status.mockResolvedValue(makeStatus());
    mocked.withdraw.mockResolvedValue({ withdrawn: true });
  });

  it("renders the timeline for an under-review application", async () => {
    render(<StatusPage />);
    expect(
      await screen.findByRole("heading", { name: "Senior Frontend Engineer" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Marta Vidal")).toBeInTheDocument();
    expect(screen.getByText("marta-vidal-cv.pdf")).toBeInTheDocument();
    expect(screen.getByText("Application received")).toBeInTheDocument();
    expect(screen.getByText("Assessment completed")).toBeInTheDocument();
    expect(screen.getByText(/12 of 12 answered/)).toBeInTheDocument();
    expect(screen.getByText("Under review")).toBeInTheDocument();
    expect(screen.getByText(/within two weeks/)).toBeInTheDocument();
    expect(screen.getByText("Decision")).toBeInTheDocument();
    expect(screen.getByText(/expected by/)).toBeInTheDocument();
    expect(screen.getByText(/private to you/)).toBeInTheDocument();
    // no score anywhere on a candidate surface
    expect(screen.queryByText(/%|score/i)).toBeNull();
  });

  it("skips the assessment step when the job had no quiz", async () => {
    mocked.status.mockResolvedValue(makeStatus({ quiz: null }));
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(screen.queryByText(/Assessment/)).not.toBeInTheDocument();
  });

  it("withdraws after an explicit confirm and shows the withdrawn state", async () => {
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });

    await userEvent.click(screen.getByRole("button", { name: "Withdraw application" }));
    expect(mocked.withdraw).not.toHaveBeenCalled(); // first click only arms the confirm

    mocked.status.mockResolvedValue(makeStatus({ stage: "withdrawn" }));
    await userEvent.click(screen.getByRole("button", { name: /Yes, withdraw/ }));
    await waitFor(() => expect(mocked.withdraw).toHaveBeenCalledWith("status-tok"));
    expect(await screen.findByText(/Withdrawn at your request/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Withdraw application" })).toBeNull();
  });

  it("shows the decided state without a withdraw action", async () => {
    mocked.status.mockResolvedValue(makeStatus({ stage: "rejected" }));
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(screen.getByText(/Decision made — check your email/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Withdraw application" })).toBeNull();
  });

  it("shows an invalid-link message on 404", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    mocked.status.mockRejectedValue(new ApiError(404, "Not found"));
    render(<StatusPage />);
    expect(await screen.findByText(/link is not valid/i)).toBeInTheDocument();
  });
});
