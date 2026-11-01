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
