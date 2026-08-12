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
    publicApplications: {
      status: vi.fn(),
      withdraw: vi.fn(),
      requestData: vi.fn(),
      requestDeletion: vi.fn(),
    },
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
    retention_months: 6,
    privacy_url: "https://jobs.example/c/northwind/privacy",
    ...overrides,
  };
}

describe("StatusPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.status.mockResolvedValue(makeStatus());
    mocked.withdraw.mockResolvedValue({ withdrawn: true });
    mocked.requestData.mockResolvedValue({ status: "received" });
    mocked.requestDeletion.mockResolvedValue({ status: "received" });
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

describe("StatusPage privacy actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.status.mockResolvedValue(makeStatus());
    mocked.withdraw.mockResolvedValue({ withdrawn: true });
    mocked.requestData.mockResolvedValue({ status: "received" });
    mocked.requestDeletion.mockResolvedValue({ status: "received" });
  });

  it("always shows the retention line linking the privacy notice", async () => {
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(screen.getByText(/kept for the period described in the/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "privacy notice" });
    expect(link).toHaveAttribute("href", "https://jobs.example/c/northwind/privacy");
  });

  it("request-a-copy posts and shows the receipt", async () => {
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    await userEvent.click(screen.getByRole("button", { name: "Request a copy of my data" }));
    await waitFor(() => expect(mocked.requestData).toHaveBeenCalledWith("status-tok"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "We've sent your request to Northwind Robotics. They'll respond within a month.",
    );
  });

  it("request-deletion posts and shows the receipt", async () => {
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    await userEvent.click(
      screen.getByRole("button", { name: "Ask for my data to be deleted" }),
    );
    await waitFor(() => expect(mocked.requestDeletion).toHaveBeenCalledWith("status-tok"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "We've sent your request to Northwind Robotics.",
    );
  });

  it("withdrawn stage adds the honest retention line", async () => {
    mocked.status.mockResolvedValue(makeStatus({ stage: "withdrawn" }));
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(
      screen.getByText(
        /Northwind Robotics keeps your data for up to 6 months unless you request deletion/,
      ),
    ).toBeInTheDocument();
  });

  it("request failure lands in the error alert", async () => {
    mocked.requestData.mockRejectedValue(new Error("Too many requests"));
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    await userEvent.click(screen.getByRole("button", { name: "Request a copy of my data" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests");
  });
});
