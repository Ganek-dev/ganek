import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { applications } from "@/lib/api";

import { StageEmailDialog } from "./StageEmailDialog";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    applications: { ...original.applications, emailPreview: vi.fn() },
  };
});

const mockedApps = vi.mocked(applications);

const REJECTION = {
  kind: "rejection" as const,
  subject: "Your application to ACME",
  text: "Thank you, Jane\n\nWe've finished reviewing applications.",
  html: "<h1>x</h1>",
};

function renderDialog(
  stage: "interview" | "rejected",
  handlers = { onConfirm: vi.fn(), onCancel: vi.fn() },
) {
  render(
    <StageEmailDialog
      open
      applicationId="app-1"
      candidateName="Jane Applicant"
      stage={stage}
      onConfirm={handlers.onConfirm}
      onCancel={handlers.onCancel}
    />,
  );
  return handlers;
}

describe("StageEmailDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApps.emailPreview.mockResolvedValue(REJECTION);
  });

  it("shows the subject and the text of the rejection email", async () => {
    renderDialog("rejected");
    expect(await screen.findByText("Your application to ACME")).toBeInTheDocument();
    expect(screen.getByTestId("stage-email-text")).toHaveTextContent("Thank you, Jane");
    expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "rejection");
    expect(screen.getByRole("button", { name: "Reject and send email" })).toBeEnabled();
    expect(screen.getByRole("dialog", { name: "Email to Jane Applicant" })).toBeInTheDocument();
  });

  it("asks for the interview email on an interview move", async () => {
    mockedApps.emailPreview.mockResolvedValue({
      ...REJECTION,
      kind: "stage_advance",
      subject: "Next step: interviews at ACME",
    });
    renderDialog("interview");
    expect(await screen.findByText("Next step: interviews at ACME")).toBeInTheDocument();
    expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "stage_advance");
    expect(
      screen.getByRole("button", { name: "Move to Interview and send email" }),
    ).toBeEnabled();
  });

  it("confirm and cancel call back", async () => {
    const { onConfirm, onCancel } = renderDialog("rejected");
    await screen.findByText("Your application to ACME");
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("shows an error and still lets the recruiter confirm", async () => {
    mockedApps.emailPreview.mockRejectedValue(new Error("boom"));
    const { onConfirm } = renderDialog("rejected");
    expect(await screen.findByRole("alert")).toHaveTextContent("Preview unavailable");
    const confirm = screen.getByRole("button", { name: "Reject and send email" });
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("shows a skeleton while loading and keeps confirm disabled", async () => {
    mockedApps.emailPreview.mockReturnValue(new Promise(() => {}));
    renderDialog("rejected");
    expect(await screen.findByLabelText("Loading preview")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reject and send email" })).toBeDisabled(),
    );
  });
});
