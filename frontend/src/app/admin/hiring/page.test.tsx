import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { companyApi, type CompanyAdmin } from "@/lib/api";

import HiringSettingsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/hiring",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: { get: vi.fn(), updateBranding: vi.fn(), updateSettings: vi.fn() },
  };
});

const mocked = vi.mocked(companyApi);

function makeCompany(settings: CompanyAdmin["settings"] = {}): CompanyAdmin {
  return {
    screening_questions: [],
    slug: "acmelabs",
    mode: "single" as const,
    smtp_configured: true,
    name: "Acme Labs",
    description: "",
    logo_url: null,
    website: null,
    socials: {},
    theme: {},
    settings,
  };
}

describe("HiringSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(makeCompany());
    mocked.updateSettings.mockResolvedValue(makeCompany({ quiz_expired_reissue: "auto" }));
  });

  it("defaults to manual when no setting is stored", async () => {
    render(<HiringSettingsPage />);
    expect(await screen.findByRole("radio", { name: /Ask the team first/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("hydrates a stored auto setting", async () => {
    mocked.get.mockResolvedValue(makeCompany({ quiz_expired_reissue: "auto" }));
    render(<HiringSettingsPage />);
    expect(
      await screen.findByRole("radio", { name: /Re-issue automatically/ }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("saves auto, and manual as null (reset to default)", async () => {
    render(<HiringSettingsPage />);
    await userEvent.click(await screen.findByRole("radio", { name: /Re-issue automatically/ }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({ quiz_expired_reissue: "auto" }),
    );
    await userEvent.click(screen.getByRole("radio", { name: /Ask the team first/ }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({ quiz_expired_reissue: null }),
    );
  });

  it("rolls the selection back when saving fails", async () => {
    mocked.updateSettings.mockRejectedValue(new Error("boom"));
    render(<HiringSettingsPage />);
    await userEvent.click(await screen.findByRole("radio", { name: /Re-issue automatically/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByRole("radio", { name: /Ask the team first/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});

describe("HiringSettingsPage default screening questions", () => {
  const PERMIT = {
    id: "sq_0000aa01",
    type: "yes_no" as const,
    prompt: "Can you work in Germany?",
    options: null,
    preferred: "yes",
    required: true,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue({ ...makeCompany(), screening_questions: [PERMIT] });
    mocked.updateSettings.mockResolvedValue({ ...makeCompany(), screening_questions: [] });
  });

  it("loads the company set into the editor and explains the copy rule", async () => {
    render(<HiringSettingsPage />);
    expect(await screen.findByLabelText("Prompt")).toHaveValue("Can you work in Germany?");
    expect(
      screen.getByText("New jobs start with these. Existing jobs keep their own list."),
    ).toBeInTheDocument();
  });

  it("saves the edited set as the whole list", async () => {
    render(<HiringSettingsPage />);
    await screen.findByLabelText("Prompt");
    await userEvent.click(screen.getByRole("button", { name: "Remove question 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Save default questions" }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({ screening_questions: [] }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });
});

describe("HiringSettingsPage default scorecard", () => {
  const CRIT = { id: "aaaaaaaa", label: "Problem solving", hint: "" };

  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue({ ...makeCompany(), scorecard_template: [CRIT] });
    mocked.updateSettings.mockResolvedValue({ ...makeCompany(), scorecard_template: [CRIT] });
  });

  it("loads the company template and saves the whole list with ids intact", async () => {
    render(<HiringSettingsPage />);
    expect(await screen.findByLabelText("Criterion label")).toHaveValue("Problem solving");
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    await userEvent.type(screen.getAllByLabelText("Criterion label")[1]!, "Design");
    await userEvent.click(screen.getByRole("button", { name: "Save default scorecard" }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({
        scorecard_template: [CRIT, { id: "", label: "Design", hint: "" }],
      }),
    );
  });

  it("explains the copy rule and shows the empty hint", async () => {
    mocked.get.mockResolvedValue({ ...makeCompany(), scorecard_template: [] });
    render(<HiringSettingsPage />);
    expect(await screen.findByText("New jobs copy these criteria.")).toBeInTheDocument();
  });
});

describe("HiringSettingsPage blank scorecard label", () => {
  it("blocks the save until the label is filled in", async () => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue({ ...makeCompany(), scorecard_template: [] });
    mocked.updateSettings.mockResolvedValue({ ...makeCompany(), scorecard_template: [] });
    render(<HiringSettingsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add criterion" }));
    await userEvent.click(screen.getByRole("button", { name: "Save default scorecard" }));
    expect(mocked.updateSettings).not.toHaveBeenCalled();
    expect(screen.getByText("Label is required")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Criterion label"), "Design");
    await userEvent.click(screen.getByRole("button", { name: "Save default scorecard" }));
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({
        scorecard_template: [{ id: "", label: "Design", hint: "" }],
      }),
    );
  });
});

describe("HiringSettingsPage pipeline", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(makeCompany());
    mocked.updateSettings.mockResolvedValue(makeCompany());
  });

  it("shows the stage limit from settings and saves a new value", async () => {
    const user = userEvent.setup();
    mocked.updateSettings.mockResolvedValue(makeCompany({ stage_limit_days: 14 }));
    render(<HiringSettingsPage />);
    const input = await screen.findByLabelText("Flag a candidate as overdue after");
    expect(input).toHaveValue(7);
    await user.clear(input);
    await user.type(input, "14");
    await user.tab();
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({ stage_limit_days: 14 }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });

  it("hydrates a stored stage limit and sends nothing when it did not change", async () => {
    const user = userEvent.setup();
    mocked.get.mockResolvedValue(makeCompany({ stage_limit_days: 10 }));
    render(<HiringSettingsPage />);
    const input = await screen.findByLabelText("Flag a candidate as overdue after");
    await waitFor(() => expect(input).toHaveValue(10));
    await user.click(input);
    await user.tab();
    expect(mocked.updateSettings).not.toHaveBeenCalled();
  });

  it("saves on Enter", async () => {
    const user = userEvent.setup();
    mocked.updateSettings.mockResolvedValue(makeCompany({ stage_limit_days: 3 }));
    render(<HiringSettingsPage />);
    const input = await screen.findByLabelText("Flag a candidate as overdue after");
    await user.clear(input);
    await user.type(input, "3{Enter}");
    await waitFor(() =>
      expect(mocked.updateSettings).toHaveBeenCalledWith({ stage_limit_days: 3 }),
    );
  });

  it("rejects 0 and 61 inline without a request", async () => {
    const user = userEvent.setup();
    render(<HiringSettingsPage />);
    const input = await screen.findByLabelText("Flag a candidate as overdue after");
    await user.clear(input);
    await user.type(input, "0");
    await user.tab();
    expect(await screen.findByText("Enter a whole number from 1 to 60.")).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "61");
    await user.tab();
    expect(screen.getByText("Enter a whole number from 1 to 60.")).toBeInTheDocument();
    expect(mocked.updateSettings).not.toHaveBeenCalled();
  });

  it("keeps the typed value and shows the error when the save fails", async () => {
    const user = userEvent.setup();
    mocked.updateSettings.mockRejectedValue(new Error("Boom"));
    render(<HiringSettingsPage />);
    const input = await screen.findByLabelText("Flag a candidate as overdue after");
    await user.clear(input);
    await user.type(input, "20");
    await user.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
    expect(input).toHaveValue(20);
  });

  it("clears a stale save error when the next value is out of range", async () => {
    const user = userEvent.setup();
    mocked.updateSettings.mockRejectedValue(new Error("Boom"));
    render(<HiringSettingsPage />);
    const input = await screen.findByLabelText("Flag a candidate as overdue after");
    await user.clear(input);
    await user.type(input, "20");
    await user.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
    await user.clear(input);
    await user.type(input, "0");
    await user.tab();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(input).toHaveAccessibleDescription(/Enter a whole number from 1 to 60\./);
  });
});
