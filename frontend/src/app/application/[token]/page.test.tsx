import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { publicApplications, publicApply, type ApplicationStatus } from "@/lib/api";

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
      cvUploadTicket: vi.fn(),
      replaceCv: vi.fn(),
    },
  };
});

const mocked = vi.mocked(publicApplications);

function makeStatus(overrides: Partial<ApplicationStatus> = {}): ApplicationStatus {
  return {
    company_name: "ACME Ganek",
    brand_primary: "#3d5afe",
    job_title: "Senior Frontend Engineer",
    candidate_name: "Marta Vidal",
    cv_filename: "marta-vidal-cv.pdf",
    applied_at: "2026-07-24T14:58:00Z",
    stage: "screening",
    quiz: {
      status: "completed",
      answered: 12,
      timed_out: 0,
      total: 12,
      completed_at: "2026-07-24T15:12:00Z",
    },
    decision_expected_by: "2026-08-07",
    decision_overdue: false,
    retention_months: 6,
    privacy_url: "https://jobs.example/c/acme/privacy",
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
    expect(screen.getByText(/hear back by email, either way/)).toBeInTheDocument();
    expect(screen.queryByText(/two weeks/)).toBeNull();
    expect(screen.getByText("Decision")).toBeInTheDocument();
    // the server's day, read as that calendar day in any time zone
    expect(screen.getByText("expected by Aug 7")).toBeInTheDocument();
    expect(screen.getByText(/private to you/)).toBeInTheDocument();
    // no score anywhere on a candidate surface
    expect(screen.queryByText(/%|score/i)).toBeNull();
  });

  it("says the team is running late once the decision date has passed", async () => {
    mocked.status.mockResolvedValue(makeStatus({ decision_overdue: true }));
    render(<StatusPage />);
    expect(
      await screen.findByText(/planned for Aug 7 - running late, you'll still hear back by email/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/expected by/)).toBeNull();
  });

  it("shows timed-out questions separately in the assessment step", async () => {
    mocked.status.mockResolvedValue(
      makeStatus({
        quiz: {
          status: "completed",
          answered: 6,
          timed_out: 2,
          total: 8,
          completed_at: "2026-07-24T15:12:00Z",
        },
      }),
    );
    render(<StatusPage />);
    expect(await screen.findByText(/6 answered, 2 timed out/)).toBeInTheDocument();
    expect(screen.queryByText(/8 of 8 answered/)).not.toBeInTheDocument();
  });

  it("lists interview rounds in order with their state", async () => {
    mocked.status.mockResolvedValue(
      makeStatus({
        interviews: [
          {
            round_number: 1,
            status: "booked",
            completed: true,
            title: "Hiring manager interview",
            scheduled_start: "2026-07-28T09:00:00Z",
            duration_minutes: 30,
          },
          {
            round_number: 2,
            status: "pending",
            completed: false,
            title: "Team interview",
            scheduled_start: null,
            duration_minutes: 45,
          },
        ],
      }),
    );
    render(<StatusPage />);
    const first = await screen.findByText("Interview round 1 completed");
    const second = screen.getByText("Interview round 2");
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Pick a time from the link in your email.")).toBeInTheDocument();
  });

  it("labels a single interview without a round number", async () => {
    mocked.status.mockResolvedValue(
      makeStatus({
        interviews: [
          {
            round_number: 1,
            status: "booked",
            completed: false,
            title: "Hiring manager interview",
            scheduled_start: "2027-01-05T13:00:00Z",
            duration_minutes: 30,
          },
        ],
      }),
    );
    render(<StatusPage />);
    expect(await screen.findByText("Interview")).toBeInTheDocument();
    expect(screen.getByText(/30 min/)).toBeInTheDocument();
    expect(screen.queryByText(/round/)).toBeNull();
  });

  it("skips the assessment step when the job had no quiz", async () => {
    mocked.status.mockResolvedValue(makeStatus({ quiz: null }));
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(screen.queryByText(/Assessment/)).not.toBeInTheDocument();
  });

  it("leaves the CV out of the header for an application without one", async () => {
    mocked.status.mockResolvedValue(makeStatus({ cv_filename: null }));
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(screen.queryByText("marta-vidal-cv.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("Marta Vidal")).toBeInTheDocument();
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
    expect(screen.getByText(/Decision made - check your email/)).toBeInTheDocument();
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
    expect(link).toHaveAttribute("href", "https://jobs.example/c/acme/privacy");
  });

  it("request-a-copy posts and shows the receipt", async () => {
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    await userEvent.click(screen.getByRole("button", { name: "Request a copy of my data" }));
    await waitFor(() => expect(mocked.requestData).toHaveBeenCalledWith("status-tok"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "We've sent your request to ACME Ganek. They'll respond within a month.",
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
      "We've sent your request to ACME Ganek.",
    );
  });

  it("withdrawn stage adds the honest retention line", async () => {
    mocked.status.mockResolvedValue(makeStatus({ stage: "withdrawn" }));
    render(<StatusPage />);
    await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
    expect(
      screen.getByText(
        /ACME Ganek keeps your data for up to 6 months unless you request deletion/,
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

  describe("CV flagged by the virus scanner", () => {
    const ticket = {
      upload_url: "https://s3.example/bucket",
      upload_fields: { key: "cvs/co/new.pdf" },
      object_key: "cvs/co/new.pdf",
      content_type: "application/pdf",
      max_size_mb: 10,
    };

    beforeEach(() => {
      mocked.status.mockResolvedValue(makeStatus({ cv_reupload_requested: true }));
      mocked.cvUploadTicket.mockResolvedValue(ticket);
      mocked.replaceCv.mockResolvedValue({ replaced: true });
    });

    it("asks for a new CV, uploads it and confirms", async () => {
      const upload = vi.spyOn(publicApply, "uploadCv").mockResolvedValue(undefined);
      render(<StatusPage />);
      expect(
        await screen.findByRole("heading", { name: "Please upload your CV again" }),
      ).toBeInTheDocument();
      expect(screen.getByText(/virus scanner flagged the file you sent/)).toBeInTheDocument();
      // the signature is for the team; the page never names it
      expect(screen.queryByText(/eicar/i)).toBeNull();

      mocked.status.mockResolvedValue(makeStatus({ cv_filename: "fresh.pdf" }));
      const file = new File(["%PDF-1.4"], "fresh.pdf", { type: "application/pdf" });
      await userEvent.upload(screen.getByLabelText("Upload a new CV (PDF)"), file);

      await waitFor(() =>
        expect(mocked.replaceCv).toHaveBeenCalledWith("status-tok", {
          cv_object_key: "cvs/co/new.pdf",
          cv_filename: "fresh.pdf",
        }),
      );
      expect(mocked.cvUploadTicket).toHaveBeenCalledWith("status-tok");
      expect(upload).toHaveBeenCalledWith(ticket, file, expect.any(Function));
      expect(await screen.findByRole("status")).toHaveTextContent(
        "we received your new CV and are checking it now",
      );
      expect(screen.queryByRole("heading", { name: "Please upload your CV again" })).toBeNull();
      expect(await screen.findByText("fresh.pdf")).toBeInTheDocument();
      upload.mockRestore();
    });

    it("refuses a non-PDF before asking for a ticket", async () => {
      render(<StatusPage />);
      await screen.findByRole("heading", { name: "Please upload your CV again" });
      const file = new File(["x"], "cv.docx", { type: "application/msword" });
      await userEvent.upload(screen.getByLabelText("Upload a new CV (PDF)"), file, {
        applyAccept: false,
      });
      expect(await screen.findByRole("alert")).toHaveTextContent("Your CV must be a PDF file.");
      expect(mocked.cvUploadTicket).not.toHaveBeenCalled();
    });

    it("shows a failed replacement in the card", async () => {
      const upload = vi.spyOn(publicApply, "uploadCv").mockResolvedValue(undefined);
      mocked.replaceCv.mockRejectedValue(new Error("CV must be a PDF"));
      render(<StatusPage />);
      await screen.findByRole("heading", { name: "Please upload your CV again" });
      const file = new File(["%PDF-1.4"], "fresh.pdf", { type: "application/pdf" });
      await userEvent.upload(screen.getByLabelText("Upload a new CV (PDF)"), file);
      expect(await screen.findByRole("alert")).toHaveTextContent("CV must be a PDF");
      expect(screen.getByRole("heading", { name: "Please upload your CV again" })).toBeInTheDocument();
      upload.mockRestore();
    });

    it("does not show the card when no new CV is needed", async () => {
      mocked.status.mockResolvedValue(makeStatus());
      render(<StatusPage />);
      await screen.findByRole("heading", { name: "Senior Frontend Engineer" });
      expect(screen.queryByRole("heading", { name: "Please upload your CV again" })).toBeNull();
    });
  });
});
