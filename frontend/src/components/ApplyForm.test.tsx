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
      upload_url: "http://minio.test/ganek-cvs",
      upload_fields: { key: "cvs/co/abc.pdf", policy: "p", "Content-Type": "application/pdf" },
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

  it("sends the resolved source with the application, null when none was given", async () => {
    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });
    const { unmount } = render(
      <ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" source="linkedin" />,
    );
    await fillAndUpload(file);
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));
    expect(await screen.findByText(/Application received/)).toBeInTheDocument();
    expect(mocked.submit).toHaveBeenLastCalledWith(
      "/api/v1/public/company/jobs/dev",
      expect.objectContaining({ source: "linkedin" }),
    );
    // the value is static markup, never typed by the candidate
    expect(screen.queryByRole("textbox", { name: /source/i })).not.toBeInTheDocument();
    unmount();

    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    await fillAndUpload(file);
    await userEvent.click(screen.getByRole("button", { name: "Submit application" }));
    expect(await screen.findByText(/Application received/)).toBeInTheDocument();
    expect(mocked.submit).toHaveBeenLastCalledWith(
      "/api/v1/public/company/jobs/dev",
      expect.objectContaining({ source: null }),
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
    expect(screen.getByText(/tab switches, pastes & resizes are recorded/)).toBeInTheDocument();
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

  it("shows the privacy notice line above submit — a link, never a checkbox", () => {
    render(
      <ApplyForm
        apiBasePath="/api/v1/public/company/jobs/dev"
        companyName="Acme Labs"
        privacyHref="/privacy"
      />,
    );
    expect(screen.getByText(/By applying, Acme Labs processes your details/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "privacy notice" })).toHaveAttribute(
      "href",
      "/privacy",
    );
    // the basis is art. 6(1)(b) — there must be no consent checkbox
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("renders no legal block when no privacyHref is wired", () => {
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    expect(screen.queryByText(/privacy notice/)).toBeNull();
  });

  it("nudges candidates to leave sensitive details out of the message", () => {
    render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/dev" />);
    expect(
      screen.getByText(/leave out sensitive personal details/i),
    ).toBeInTheDocument();
  });

  describe("demo instance", () => {
    it("has no CV field and says nothing typed is kept", () => {
      render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/x" demo />);
      expect(screen.queryByLabelText("CV (PDF)")).toBeNull();
      expect(screen.getByText("CV upload is off on the demo")).toBeInTheDocument();
      expect(screen.getByRole("note")).toHaveTextContent("Nothing you type is kept");
      expect(mocked.uploadTicket).not.toHaveBeenCalled();
    });

    it("submits without a CV and shows the assessment link on screen", async () => {
      mocked.submit.mockResolvedValue({
        status: "received",
        quiz_token: "qt-demo",
        status_token: "st-demo",
      });
      render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/x" demo />);
      await fillAndUpload();
      await userEvent.click(screen.getByRole("button", { name: "Submit application" }));

      expect(mocked.submit).toHaveBeenCalledTimes(1);
      const payload = mocked.submit.mock.calls[0]![1];
      expect(payload).not.toHaveProperty("cv_object_key");
      expect(payload).not.toHaveProperty("cv_filename");
      expect(payload.name).toBe("Jane Doe");
      expect(await screen.findByRole("link", { name: "Start assessment now" })).toHaveAttribute(
        "href",
        "/quiz/qt-demo",
      );
      expect(
        screen.getByText("On the demo your link appears here instead of in an inbox:"),
      ).toBeInTheDocument();
    });

    it("still requires a CV outside demo mode", async () => {
      render(<ApplyForm apiBasePath="/api/v1/public/company/jobs/x" />);
      await fillAndUpload();
      await userEvent.click(screen.getByRole("button", { name: "Submit application" }));
      expect(screen.getByRole("alert")).toHaveTextContent("Please attach your CV as a PDF.");
      expect(mocked.submit).not.toHaveBeenCalled();
    });
  });
});
