import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, companyApi, team, type JobOut, type TeamUser } from "@/lib/api";

import { OnboardingChecklist } from "./OnboardingChecklist";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, me: vi.fn(), jobs: { ...original.api.jobs, list: vi.fn() } },
    companyApi: { get: vi.fn(), updateBranding: vi.fn() },
    team: {
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      listInvites: vi.fn(),
      invite: vi.fn(),
      resendInvite: vi.fn(),
      revokeInvite: vi.fn(),
    },
  };
});

const mockedApi = vi.mocked(api);
const mockedCompany = vi.mocked(companyApi);
const mockedTeam = vi.mocked(team);
const mockedJobs = vi.mocked(api.jobs);

const admin = { id: "u1", company_id: "c1", email: "a@x.dev", role: "admin" as const };
const soloTeam: TeamUser[] = [
  {
    id: "u1",
    email: "a@x.dev",
    role: "admin",
    is_active: true,
    last_login_at: null,
    created_at: "2026-08-01T00:00:00Z",
  },
];

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "j1",
    slug: "engineer",
    title: "Engineer",
    description_md: "",
    location: "",
    remote_policy: "remote",
    employment_type: "full_time",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    tags: [],
    status: "draft",
    quiz_config: {
      enabled: false,
      tags: null,
      question_count: 6,
      include_company_questions: true,
      time_limit_seconds: 20,
      difficulties: null,
      exclude_ids: [],
      questionnaire_id: null,
    },
    published_at: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function mockState({
  theme = {},
  jobs = [] as JobOut[],
  users = soloTeam,
  invites = [] as { id: string }[],
} = {}) {
  mockedApi.me.mockResolvedValue(admin);
  mockedCompany.get.mockResolvedValue({
    slug: "acmelabs",
    name: "Acme Labs",
    description: "",
    logo_url: null,
    website: null,
    socials: {},
    theme,
  });
  mockedJobs.list.mockResolvedValue(jobs);
  mockedTeam.list.mockResolvedValue(users);
  mockedTeam.listInvites.mockResolvedValue(
    invites.map((invite) => ({
      ...invite,
      email: "x@x.dev",
      role: "member" as const,
      created_at: "2026-08-01T00:00:00Z",
      expires_at: "2026-08-08T00:00:00Z",
    })),
  );
}

describe("OnboardingChecklist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the five steps with progress and CTAs on a fresh workspace", async () => {
    mockState();
    render(<OnboardingChecklist />);
    expect(await screen.findByText("Let's get Acme Labs hiring")).toBeInTheDocument();
    expect(screen.getByText("1 of 5 done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open branding" })).toHaveAttribute(
      "href",
      "/admin/branding",
    );
    expect(screen.getByRole("link", { name: "Create job" })).toHaveAttribute(
      "href",
      "/admin/jobs/new",
    );
    expect(screen.getByRole("link", { name: "Browse questions" })).toHaveAttribute(
      "href",
      "/admin/questions",
    );
    expect(screen.getByRole("link", { name: "Invite" })).toHaveAttribute("href", "/admin/team");
    expect(screen.getByText("acmelabs.vetd.dev")).toBeInTheDocument();
  });

  it("derives progress from branding, jobs, assessments, and invites", async () => {
    mockState({
      theme: { primary_color: "#7E14FF" },
      jobs: [makeJob({ quiz_config: { ...makeJob().quiz_config, enabled: true } })],
      invites: [{ id: "i1" }],
    });
    render(<OnboardingChecklist />);
    // all five done → the checklist retires itself
    await waitFor(() => expect(mockedTeam.listInvites).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByTestId("onboarding-checklist")).not.toBeInTheDocument(),
    );
  });

  it("counts partial progress", async () => {
    mockState({ jobs: [makeJob()] });
    render(<OnboardingChecklist />);
    expect(await screen.findByText("2 of 5 done")).toBeInTheDocument();
    // job exists without an assessment: step 4 still offers its CTA
    expect(screen.getByRole("link", { name: "Browse questions" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create job" })).not.toBeInTheDocument();
  });

  it("renders nothing for members", async () => {
    mockedApi.me.mockResolvedValue({ ...admin, role: "member" });
    render(<OnboardingChecklist />);
    await waitFor(() => expect(mockedApi.me).toHaveBeenCalled());
    expect(screen.queryByTestId("onboarding-checklist")).not.toBeInTheDocument();
    expect(mockedCompany.get).not.toHaveBeenCalled();
  });

  it("renders nothing when loading fails", async () => {
    mockedApi.me.mockRejectedValue(new Error("boom"));
    render(<OnboardingChecklist />);
    await waitFor(() => expect(mockedApi.me).toHaveBeenCalled());
    expect(screen.queryByTestId("onboarding-checklist")).not.toBeInTheDocument();
  });
});
