import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { applications, emailTemplates, type EmailKindInfo } from "@/lib/api";

import { StageEmailDialog } from "./StageEmailDialog";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    applications: { ...original.applications, emailPreview: vi.fn() },
    emailTemplates: { ...original.emailTemplates, list: vi.fn() },
  };
});

const mockedApps = vi.mocked(applications);
const mockedTemplates = vi.mocked(emailTemplates);

function kinds(rejection: EmailKindInfo["templates"]): { kinds: EmailKindInfo[] } {
  const base = { placeholders: [], builtin: { subject: "s", body: "b" }, templates: [] };
  return {
    kinds: [
      { kind: "quiz_invite", label: "Assessment invite", ...base },
      { kind: "quiz_reminder", label: "Assessment reminder", ...base },
      { kind: "stage_advance", label: "Interview", ...base },
      { kind: "rejection", label: "Rejection", ...base, templates: rejection },
    ],
  };
}

function tpl(id: string, name: string, is_default = false): EmailKindInfo["templates"][number] {
  return {
    id,
    kind: "rejection",
    name,
    subject: "s",
    body: "b",
    is_default,
    created_at: "",
    updated_at: "",
  };
}

const REJECTION = {
  kind: "rejection" as const,
  subject: "Your application to ACME",
  text: "Thank you, Jane\n\nWe've finished reviewing applications.\n\nSee open positions: https://x",
  html: "<h1>x</h1>",
  body: "Thank you, Jane\n\nWe've finished reviewing applications.",
};

function renderDialog(
  stage: "interview" | "rejected",
  handlers = { onConfirm: vi.fn(), onCancel: vi.fn() },
  email = true,
) {
  render(
    <StageEmailDialog
      open
      applicationId="app-1"
      candidateName="Jane Applicant"
      stage={stage}
      email={email}
      onConfirm={handlers.onConfirm}
      onCancel={handlers.onCancel}
    />,
  );
  return handlers;
}

const NO_FIELDS = { rejectionReason: null, rejectionNote: null };

describe("StageEmailDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApps.emailPreview.mockResolvedValue(REJECTION);
    mockedTemplates.list.mockResolvedValue(kinds([]));
  });

  it("shows the subject and the text of the rejection email", async () => {
    renderDialog("rejected");
    expect(await screen.findByText("Your application to ACME")).toBeInTheDocument();
    expect(screen.getByTestId("stage-email-text")).toHaveTextContent("Thank you, Jane");
    expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "rejection", undefined);
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
    expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "stage_advance", undefined);
    expect(
      screen.getByRole("button", { name: "Move to Interview and send email" }),
    ).toBeEnabled();
  });

  it("confirm and cancel call back", async () => {
    const { onConfirm, onCancel } = renderDialog("rejected");
    await screen.findByText("Your application to ACME");
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith(NO_FIELDS);
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
    expect(onConfirm).toHaveBeenCalledWith(NO_FIELDS);
  });

  it("shows a skeleton while loading and keeps confirm disabled", async () => {
    mockedApps.emailPreview.mockReturnValue(new Promise(() => {}));
    renderDialog("rejected");
    expect(await screen.findByLabelText("Loading preview")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reject and send email" })).toBeDisabled(),
    );
  });

  it("offers the reason picklist and note on a rejection and passes them to confirm", async () => {
    const { onConfirm } = renderDialog("rejected");
    await screen.findByText("Your application to ACME");
    const select = screen.getByRole("combobox", { name: "Reason (internal, optional)" });
    const labels = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(labels).toEqual([
      "No reason recorded",
      "Another candidate preferred",
      "Skills below the bar",
      "Salary expectations did not match",
      "Location or work permit",
      "No response from the candidate",
      "Other",
    ]);
    await userEvent.selectOptions(select, "Skills below the bar");
    await userEvent.type(screen.getByLabelText("Internal note"), "  Take-home below the bar  ");
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    expect(onConfirm).toHaveBeenCalledWith({
      rejectionReason: "skills_gap",
      rejectionNote: "Take-home below the bar",
    });
  });

  it("sends nulls when nothing was picked", async () => {
    const { onConfirm } = renderDialog("rejected");
    await screen.findByText("Your application to ACME");
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    expect(onConfirm).toHaveBeenCalledWith(NO_FIELDS);
  });

  it("rejects without an email when the checkbox was off", async () => {
    const { onConfirm } = renderDialog("rejected", undefined, false);
    expect(screen.getByRole("dialog", { name: "Reject Jane Applicant" })).toBeInTheDocument();
    expect(screen.getByText("No email will be sent.")).toBeInTheDocument();
    expect(mockedApps.emailPreview).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Loading preview")).not.toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Reason (internal, optional)" }),
      "Another candidate preferred",
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onConfirm).toHaveBeenCalledWith({ rejectionReason: "another_candidate", rejectionNote: null });
  });

  it("shows no reason fields on an interview move", async () => {
    renderDialog("interview");
    await screen.findByText("Your application to ACME");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Internal note")).not.toBeInTheDocument();
  });

  it("shows the helper line about data requests", async () => {
    renderDialog("rejected");
    await screen.findByText("Your application to ACME");
    expect(
      screen.getByText("Internal: not emailed. Included if the candidate requests their data, so keep it factual."),
    ).toBeInTheDocument();
  });

  it("hides the template select when only the Ganek default exists", async () => {
    renderDialog("rejected");
    await screen.findByText("Your application to ACME");
    expect(screen.queryByRole("combobox", { name: "Template" })).not.toBeInTheDocument();
    expect(mockedApps.emailPreview).toHaveBeenCalledTimes(1);
    expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "rejection", undefined);
  });

  it("offers the templates with the default preselected and refetches the preview on change", async () => {
    mockedTemplates.list.mockResolvedValue(kinds([tpl("t-a", "A"), tpl("t-b", "B", true)]));
    const { onConfirm } = renderDialog("rejected");
    const select = await screen.findByRole("combobox", { name: "Template" });
    expect(select).toHaveValue("t-b");
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual([
      "Ganek default",
      "A",
      "B",
    ]);
    await waitFor(() => expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "rejection", "t-b"));
    await userEvent.selectOptions(select, "Ganek default");
    await waitFor(() =>
      expect(mockedApps.emailPreview).toHaveBeenCalledWith("app-1", "rejection", "builtin"),
    );
    await screen.findByText("Your application to ACME");
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    expect(onConfirm).toHaveBeenCalledWith({ ...NO_FIELDS, templateId: "builtin" });
  });

  it("Edit this email prefills the subject and the body from the preview and sends them as overrides", async () => {
    const { onConfirm } = renderDialog("rejected");
    await screen.findByTestId("stage-email-text");
    await userEvent.click(screen.getByRole("button", { name: "Edit this email" }));
    const subject = screen.getByRole("textbox", { name: "Subject" });
    const body = screen.getByRole("textbox", { name: "Body" });
    expect(subject).toHaveValue("Your application to ACME");
    expect(body).toHaveValue(REJECTION.body);
    expect(
      screen.getByText("Edited for this send. The link and the privacy footer are always added by Ganek."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("stage-email-text")).not.toBeInTheDocument();
    await userEvent.type(subject, " - personal");
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    expect(onConfirm).toHaveBeenCalledWith({
      ...NO_FIELDS,
      subject: "Your application to ACME - personal",
      body: REJECTION.body,
    });
  });

  it("Use the template text leaves edit mode and sends no overrides", async () => {
    const { onConfirm } = renderDialog("rejected");
    await screen.findByTestId("stage-email-text");
    await userEvent.click(screen.getByRole("button", { name: "Edit this email" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Body" }), " more");
    await userEvent.click(screen.getByRole("button", { name: "Use the template text" }));
    expect(await screen.findByTestId("stage-email-text")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reject and send email" }));
    expect(onConfirm).toHaveBeenCalledWith(NO_FIELDS);
  });

  it("keeps confirm disabled while an edited field is blank and disables the template select", async () => {
    mockedTemplates.list.mockResolvedValue(kinds([tpl("t-a", "Warm no"), tpl("t-b", "Short", true)]));
    renderDialog("rejected");
    await screen.findByTestId("stage-email-text");
    await userEvent.click(screen.getByRole("button", { name: "Edit this email" }));
    expect(screen.getByRole("combobox", { name: "Template" })).toBeDisabled();
    const body = screen.getByRole("textbox", { name: "Body" });
    await userEvent.clear(body);
    expect(screen.getByRole("button", { name: "Reject and send email" })).toBeDisabled();
    await userEvent.type(body, "Back again");
    expect(screen.getByRole("button", { name: "Reject and send email" })).toBeEnabled();
  });
});
