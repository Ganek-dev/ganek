import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { emailTemplates, type EmailKindInfo, type EmailTemplate } from "@/lib/api";

import EmailsSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/emails",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    emailTemplates: {
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
      setDefault: vi.fn(),
      setBuiltinDefault: vi.fn(),
      preview: vi.fn(),
    },
  };
});

const mocked = vi.mocked(emailTemplates);

function template(overrides: Partial<EmailTemplate>): EmailTemplate {
  return {
    id: "t-a",
    kind: "rejection",
    name: "A",
    subject: "About {{job_title}}",
    body: "Thanks {{candidate_first_name}}\n\nNot this time.",
    is_default: false,
    created_at: "2026-10-30T10:00:00Z",
    updated_at: "2026-10-30T10:00:00Z",
    ...overrides,
  };
}

const KINDS: EmailKindInfo[] = [
  {
    kind: "quiz_invite",
    label: "Assessment invite",
    placeholders: ["candidate_name", "question_count"],
    builtin: { subject: "Your {{company_name}} assessment - one step left", body: "One step left" },
    templates: [],
  },
  {
    kind: "quiz_reminder",
    label: "Assessment reminder",
    placeholders: ["candidate_name", "days_left_phrase"],
    builtin: { subject: "Your assessment link expires {{expires_phrase}}", body: "Still in" },
    templates: [],
  },
  {
    kind: "stage_advance",
    label: "Interview",
    placeholders: ["candidate_name"],
    builtin: { subject: "Next step: interviews at {{company_name}}", body: "Good news" },
    templates: [],
  },
  {
    kind: "rejection",
    label: "Rejection",
    placeholders: ["candidate_name", "assessment_thanks"],
    builtin: { subject: "Your application to {{company_name}}", body: "Thank you, {{candidate_name}}" },
    templates: [template({ id: "t-a", name: "A" }), template({ id: "t-b", name: "B", is_default: true })],
  },
];

function section(name: string) {
  return screen.getByRole("region", { name });
}

describe("EmailsSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.list.mockResolvedValue({ kinds: KINDS });
    mocked.setDefault.mockResolvedValue(template({ id: "t-a", is_default: true }));
    mocked.remove.mockResolvedValue(undefined);
    mocked.setBuiltinDefault.mockResolvedValue(undefined);
  });

  it("Ganek default can be made the default again when a custom one holds it", async () => {
    render(<EmailsSettingsPage />);
    await screen.findByRole("heading", { name: "Emails" });
    const [builtin] = within(section("Rejection")).getAllByRole("listitem");
    await userEvent.click(within(builtin).getByRole("button", { name: "Set as default" }));
    await waitFor(() => expect(mocked.setBuiltinDefault).toHaveBeenCalledWith("rejection"));
    expect(await screen.findByRole("status")).toHaveTextContent("Default updated");
    const [interviewBuiltin] = within(section("Interview")).getAllByRole("listitem");
    expect(
      within(interviewBuiltin).queryByRole("button", { name: "Set as default" }),
    ).not.toBeInTheDocument();
  });

  it("lists the four kinds with Ganek default first and custom templates after", async () => {
    render(<EmailsSettingsPage />);
    expect(await screen.findByRole("heading", { name: "Emails" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Assessment invite",
      "Assessment reminder",
      "Interview",
      "Rejection",
    ]);
    const rejection = section("Rejection");
    const rows = within(rejection).getAllByRole("listitem");
    expect(rows.map((row) => within(row).getByTestId("template-name").textContent)).toEqual([
      "Ganek default",
      "A",
      "B",
    ]);
    expect(within(rows[2]).getByText("Default")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("Default")).not.toBeInTheDocument();
    const interview = section("Interview");
    const [builtin] = within(interview).getAllByRole("listitem");
    expect(within(builtin).getByText("Default")).toBeInTheDocument();
    expect(within(builtin).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(builtin).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(within(builtin).getByRole("button", { name: "Duplicate" })).toBeInTheDocument();
  });

  it("Set as default calls the endpoint and refetches", async () => {
    render(<EmailsSettingsPage />);
    await screen.findByRole("heading", { name: "Emails" });
    const [, rowA] = within(section("Rejection")).getAllByRole("listitem");
    await userEvent.click(within(rowA).getByRole("button", { name: "Set as default" }));
    await waitFor(() => expect(mocked.setDefault).toHaveBeenCalledWith("t-a"));
    await waitFor(() => expect(mocked.list).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("status")).toHaveTextContent("Default updated");
  });

  it("Delete is two-step and Keep cancels without a call", async () => {
    render(<EmailsSettingsPage />);
    await screen.findByRole("heading", { name: "Emails" });
    const [, , rowB] = within(section("Rejection")).getAllByRole("listitem");
    await userEvent.click(within(rowB).getByRole("button", { name: "Delete" }));
    expect(within(rowB).getByText("Delete B?")).toBeInTheDocument();
    await userEvent.click(within(rowB).getByRole("button", { name: "Keep" }));
    expect(mocked.remove).not.toHaveBeenCalled();
    await userEvent.click(within(rowB).getByRole("button", { name: "Delete" }));
    await userEvent.click(within(rowB).getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(mocked.remove).toHaveBeenCalledWith("t-b"));
    expect(await screen.findByRole("status")).toHaveTextContent("Template deleted");
  });

  it("shows the explainer and the active tab", async () => {
    render(<EmailsSettingsPage />);
    await screen.findByRole("heading", { name: "Emails" });
    expect(
      screen.getByText("The link and the privacy footer are always added by Ganek."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Emails" })).toHaveAttribute("aria-current", "page");
  });

  it("Duplicate on Ganek default opens the editor prefilled with the built-in text", async () => {
    mocked.preview.mockResolvedValue({ kind: "rejection", subject: "x", text: "y", html: "" });
    render(<EmailsSettingsPage />);
    await screen.findByRole("heading", { name: "Emails" });
    const [builtin] = within(section("Rejection")).getAllByRole("listitem");
    await userEvent.click(within(builtin).getByRole("button", { name: "Duplicate" }));
    const dialog = await screen.findByRole("dialog", { name: "New Rejection template" });
    expect(within(dialog).getByLabelText("Subject")).toHaveValue(
      "Your application to {{company_name}}",
    );
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Ganek default (copy)");
  });

  it("Edit opens the editor on the template and Save refetches with a flash", async () => {
    mocked.preview.mockResolvedValue({ kind: "rejection", subject: "x", text: "y", html: "" });
    mocked.update.mockResolvedValue(template({ id: "t-a" }));
    render(<EmailsSettingsPage />);
    await screen.findByRole("heading", { name: "Emails" });
    const [, rowA] = within(section("Rejection")).getAllByRole("listitem");
    await userEvent.click(within(rowA).getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit A" });
    const save = within(dialog).getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() => expect(mocked.update).toHaveBeenCalledWith("t-a", expect.anything()));
    await waitFor(() => expect(mocked.list).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("status")).toHaveTextContent("Template saved");
  });

  it("shows the error when the list fails", async () => {
    mocked.list.mockRejectedValue(new Error("boom"));
    render(<EmailsSettingsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("passes axe", async () => {
    const { container } = render(<EmailsSettingsPage />);
    await screen.findByRole("heading", { name: "Emails" });
    const results = await axe.run(container, {
      // jsdom has no layout engine: contrast needs real rendering (CI e2e territory)
      rules: { "color-contrast": { enabled: false } },
    });
    expect(
      results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    ).toEqual([]);
  });
});
