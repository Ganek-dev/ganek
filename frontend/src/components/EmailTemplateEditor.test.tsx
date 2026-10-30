import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, emailTemplates } from "@/lib/api";

import { EmailTemplateEditor } from "./EmailTemplateEditor";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    emailTemplates: {
      ...original.emailTemplates,
      create: vi.fn(),
      update: vi.fn(),
      preview: vi.fn(),
    },
  };
});

const mocked = vi.mocked(emailTemplates);
const PLACEHOLDERS = ["candidate_name", "candidate_first_name", "job_title", "company_name"];

function renderEditor(initial = { name: "", subject: "", body: "" }, id?: string) {
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  render(
    <EmailTemplateEditor
      open
      kind="rejection"
      label="Rejection"
      placeholders={PLACEHOLDERS}
      initial={{ id, ...initial }}
      onSaved={onSaved}
      onCancel={onCancel}
    />,
  );
  return { onSaved, onCancel };
}

describe("EmailTemplateEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.preview.mockImplementation(async ({ subject, body }) => ({
      kind: "rejection" as const,
      subject: subject.replace("{{candidate_first_name}}", "Alex"),
      text: body.replace("{{candidate_first_name}}", "Alex") + "\n\nSee open positions",
      html: "<p>x</p>",
    }));
    mocked.create.mockResolvedValue({
      id: "t-new",
      kind: "rejection",
      name: "Warm no",
      subject: "s",
      body: "b",
      is_default: false,
      created_at: "",
      updated_at: "",
    });
    mocked.update.mockResolvedValue({
      id: "t-a",
      kind: "rejection",
      name: "A",
      subject: "s",
      body: "b",
      is_default: false,
      created_at: "",
      updated_at: "",
    });
  });

  it("previews the text as typed and saves a new template", async () => {
    const { onSaved } = renderEditor();
    expect(screen.getByRole("dialog", { name: "New Rejection template" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name"), "Warm no");
    await userEvent.click(screen.getByLabelText("Subject"));
    await userEvent.paste("Hi {{candidate_first_name}}");
    await userEvent.type(screen.getByLabelText("Body"), "Thanks for applying.");
    await waitFor(() => expect(screen.getByText("Hi Alex")).toBeInTheDocument());
    expect(screen.getByTestId("template-preview-text")).toHaveTextContent("Thanks for applying.");
    expect(screen.getByText("The link and the privacy footer are always added by Ganek.")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() =>
      expect(mocked.create).toHaveBeenCalledWith({
        kind: "rejection",
        name: "Warm no",
        subject: "Hi {{candidate_first_name}}",
        body: "Thanks for applying.",
      }),
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("names the unknown placeholder and disables Save until it is fixed", async () => {
    mocked.preview.mockRejectedValueOnce(new ApiError(422, "Unknown placeholder: salary"));
    renderEditor({ name: "A", subject: "s", body: "Pay {{salary}}" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown placeholder: salary");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("Body"));
    await userEvent.type(screen.getByLabelText("Body"), "Pay well");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeEnabled());
  });

  it("inserts a placeholder chip at the cursor of the focused field", async () => {
    renderEditor({ name: "A", subject: "s", body: "Hi  there" });
    const body = screen.getByLabelText<HTMLTextAreaElement>("Body");
    body.focus();
    body.setSelectionRange(3, 3);
    await userEvent.click(screen.getByRole("button", { name: "{{job_title}}" }));
    expect(body.value).toBe("Hi {{job_title}} there");
    expect(body.selectionStart).toBe("Hi {{job_title}}".length);
  });

  it("keeps Save disabled while a field is blank", async () => {
    renderEditor({ name: "", subject: "s", body: "b" });
    await waitFor(() => expect(mocked.preview).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("edits an existing template through update", async () => {
    const { onSaved } = renderEditor({ name: "A", subject: "s", body: "b" }, "t-a");
    expect(screen.getByRole("dialog", { name: "Edit A" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name"), " plus");
    const save = screen.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() =>
      expect(mocked.update).toHaveBeenCalledWith("t-a", { name: "A plus", subject: "s", body: "b" }),
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("opens wide enough for the two columns", () => {
    renderEditor({ name: "A", subject: "s", body: "b" });
    const dialog = screen.getByRole("dialog", { name: "New Rejection template" });
    expect(dialog).toHaveClass("max-w-2xl");
    expect(dialog).not.toHaveClass("max-w-md");
  });

  it("Cancel calls back without saving", async () => {
    const { onCancel } = renderEditor({ name: "A", subject: "s", body: "b" });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(mocked.create).not.toHaveBeenCalled();
  });
});
