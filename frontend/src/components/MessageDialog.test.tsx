import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, applications, type MessageInput } from "@/lib/api";

import { MessageDialog } from "./MessageDialog";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    applications: { ...original.applications, messagePreview: vi.fn() },
  };
});

const mockedApps = vi.mocked(applications);

type Handlers = {
  onSend: (fields: MessageInput) => Promise<string | null>;
  onCancel: () => void;
};

function renderDialog(handlers: Handlers = { onSend: vi.fn(async () => null), onCancel: vi.fn() }) {
  render(
    <MessageDialog
      open
      applicationId="app-1"
      candidateName="Jane Applicant"
      onSend={handlers.onSend}
      onCancel={handlers.onCancel}
    />,
  );
  return handlers;
}

describe("MessageDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApps.messagePreview.mockResolvedValue({
      kind: "message",
      subject: "Quick question",
      body: "Hi Jane",
      text: "Hi Jane\n\n- ACME\n",
      html: "",
    });
  });

  it("previews the message as typed and sends the trimmed fields", async () => {
    const { onSend } = renderDialog();
    expect(screen.getByRole("dialog", { name: "Message to Jane Applicant" })).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Subject" }), "Quick question");
    await userEvent.type(screen.getByRole("textbox", { name: "Body" }), "Hi Jane ");
    await waitFor(() =>
      expect(mockedApps.messagePreview).toHaveBeenCalledWith("app-1", {
        subject: "Quick question",
        body: "Hi Jane ",
      }),
    );
    expect(await screen.findByTestId("message-preview-text")).toHaveTextContent("- ACME");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledWith({ subject: "Quick question", body: "Hi Jane" });
  });

  it("keeps Send disabled while a field is blank and shows the send error", async () => {
    const { onSend } = renderDialog({
      onSend: vi.fn(async () => "Email not configured"),
      onCancel: vi.fn(),
    });
    await userEvent.type(screen.getByRole("textbox", { name: "Subject" }), "Quick question");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Body" }), "Hi");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("Email not configured");
  });

  it("shows the preview error without blocking Send", async () => {
    mockedApps.messagePreview.mockRejectedValue(new ApiError(500, "boom"));
    renderDialog();
    await userEvent.type(screen.getByRole("textbox", { name: "Subject" }), "Quick question");
    await userEvent.type(screen.getByRole("textbox", { name: "Body" }), "Hi");
    expect(
      await screen.findByText("Preview unavailable. The message is still sent when you confirm."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });
});
