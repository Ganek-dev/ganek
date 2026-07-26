import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { publicApply } from "@/lib/api";

import { ApplyForm } from "./ApplyForm";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    publicApply: {
      uploadTicket: vi.fn(),
      uploadCv: vi.fn(),
      submit: vi.fn(),
    },
  };
});

const mocked = vi.mocked(publicApply);

async function fillAndUpload(file?: File) {
  await userEvent.type(screen.getByLabelText("Name"), "Jane Doe");
  await userEvent.type(screen.getByLabelText("Email"), "jane@example.com");
  if (file) {
    await userEvent.upload(screen.getByLabelText("CV (PDF)"), file, {
      applyAccept: false,
    });
  }
}

describe("ApplyForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.uploadTicket.mockResolvedValue({
      upload_url: "http://minio.test/put",
      object_key: "cvs/co/abc.pdf",
      content_type: "application/pdf",
      max_size_mb: 10,
    });
    mocked.uploadCv.mockResolvedValue(undefined);
    mocked.submit.mockResolvedValue({ status: "received", quiz_token: null, status_token: "st-tok" });
  });

  it("uploads the CV on selection, then submits with the ticket key", async () => {
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" jobTitle="Developer" />);
    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });
    await fillAndUpload(file);

    // upload happens on selection, before any submit
    expect(mocked.uploadTicket).toHaveBeenCalledWith("/api/v1/public/company/jobs/dev");
    expect(mocked.uploadCv).toHaveBeenCalledOnce();
    expect(await screen.findByText(/uploaded · /)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));
    expect(await screen.findByText(/Application received, Jane/)).toBeInTheDocument();
    // status magic link offered on the confirmation
    const statusLink = screen.getByRole("link", { name: /track your application/i });
    expect(statusLink).toHaveAttribute("href", "/application/st-tok");
    expect(mocked.submit).toHaveBeenCalledWith(
      "/api/v1/public/company/jobs/dev",
      expect.objectContaining({
        name: "Jane Doe",
        email: "jane@example.com",
        cv_object_key: "cvs/co/abc.pdf",
        cv_filename: "cv.pdf",
      }),
    );
  });

  it("rejects non-PDF files client-side without requesting a ticket", async () => {
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    const file = new File(["plain"], "cv.docx", { type: "text/plain" });
    await fillAndUpload(file);

    expect(await screen.findByRole("alert")).toHaveTextContent("must be a PDF");
    expect(mocked.uploadTicket).not.toHaveBeenCalled();
  });

  it("blocks submit until a CV is attached", async () => {
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    await fillAndUpload();
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("attach your CV");
    expect(mocked.submit).not.toHaveBeenCalled();
  });

  it("shows the assessment invite with quiz link and 24h copy", async () => {
    mocked.submit.mockResolvedValue({
      status: "received",
      quiz_token: "tok123",
      status_token: "st-tok",
    });
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });
    await fillAndUpload(file);
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));

    const start = await screen.findByRole("link", { name: "Start assessment now" });
    expect(start).toHaveAttribute("href", "/quiz/tok123");
    expect(screen.getByText(/next 24 hours/)).toBeInTheDocument();
    const linkBox = screen.getByLabelText("Assessment link") as HTMLInputElement;
    expect(linkBox.value).toContain("/quiz/tok123");
    expect(screen.getByText(/tab switches are recorded/)).toBeInTheDocument();
  });

  it("surfaces upload errors and lets the candidate retry", async () => {
    mocked.uploadCv.mockRejectedValueOnce(new Error("CV upload failed — please try again"));
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });
    await fillAndUpload(file);

    expect(await screen.findByRole("alert")).toHaveTextContent("upload failed");
    // retry succeeds
    await userEvent.upload(screen.getByLabelText("CV (PDF)"), file, { applyAccept: false });
    expect(await screen.findByText(/uploaded · /)).toBeInTheDocument();
  });
});
