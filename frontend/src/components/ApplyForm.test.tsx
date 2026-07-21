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
    mocked.submit.mockResolvedValue({ status: "received" });
  });

  it("uploads the CV then submits and shows confirmation", async () => {
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    await userEvent.type(screen.getByLabelText("Name"), "Jane");
    await userEvent.type(screen.getByLabelText("Email"), "jane@example.com");
    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("CV (PDF)"), file);
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));

    expect(await screen.findByText("Application received")).toBeInTheDocument();
    expect(mocked.uploadTicket).toHaveBeenCalledWith("/api/v1/public/company/jobs/dev");
    expect(mocked.uploadCv).toHaveBeenCalledOnce();
    expect(mocked.submit).toHaveBeenCalledWith(
      "/api/v1/public/company/jobs/dev",
      expect.objectContaining({
        name: "Jane",
        email: "jane@example.com",
        cv_object_key: "cvs/co/abc.pdf",
        cv_filename: "cv.pdf",
      }),
    );
  });

  it("rejects non-PDF files client-side", async () => {
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    await userEvent.type(screen.getByLabelText("Name"), "Jane");
    await userEvent.type(screen.getByLabelText("Email"), "jane@example.com");
    const file = new File(["plain"], "cv.docx", { type: "text/plain" });
    await userEvent.upload(screen.getByLabelText("CV (PDF)"), file, { applyAccept: false });
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("must be a PDF");
    expect(mocked.uploadTicket).not.toHaveBeenCalled();
  });
});
