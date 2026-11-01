import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, companyApi, stats } from "@/lib/api";

import ReviewLayout from "./layout";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/review",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      me: vi.fn(),
      logout: vi.fn(),
      providers: vi.fn(),
    },
    companyApi: { ...original.companyApi, summary: vi.fn(), get: vi.fn(), usage: vi.fn() },
    stats: { overview: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);
const mockedCompany = vi.mocked(companyApi);

const reviewer = {
  id: "u2",
  company_id: "c1",
  email: "max@acme.example",
  has_password: true,
  role: "reviewer" as const,
  display_name: "Max Berger",
  display_label: "Max Berger",
};

describe("ReviewLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.me.mockResolvedValue(reviewer);
    mockedApi.logout.mockResolvedValue(undefined);
    mockedCompany.summary.mockResolvedValue({
      slug: "acme",
      name: "Acme Labs",
      mode: "single",
      screening_questions: [],
      scorecard_template: [],
    });
  });

  it("renders the company, the title and the account menu with no admin nav", async () => {
    render(
      <ReviewLayout>
        <p>page content</p>
      </ReviewLayout>,
    );
    expect(await screen.findByText("page content")).toBeInTheDocument();
    expect(await screen.findByText("Acme Labs")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Your candidates" })).toHaveAttribute(
      "href",
      "/review",
    );
    for (const name of ["Dashboard", "Jobs", "Applicants", "Team", "Settings"]) {
      expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
    }
    // a reviewer may only call me and company summary from the shell
    expect(vi.mocked(stats.overview)).not.toHaveBeenCalled();
    expect(mockedApi.providers).not.toHaveBeenCalled();
    expect(mockedCompany.get).not.toHaveBeenCalled();
    expect(mockedCompany.usage).not.toHaveBeenCalled();
  });

  it("offers account and sign out in the menu", async () => {
    render(
      <ReviewLayout>
        <p>page content</p>
      </ReviewLayout>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Max Berger/ }));
    expect(screen.getByRole("link", { name: "Account" })).toHaveAttribute(
      "href",
      "/review/account",
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(mockedApi.logout).toHaveBeenCalled());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("redirects a staff session to /admin without rendering the page", async () => {
    mockedApi.me.mockResolvedValue({ ...reviewer, role: "member" });
    render(
      <ReviewLayout>
        <p>page content</p>
      </ReviewLayout>,
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin"));
    expect(screen.queryByText("page content")).not.toBeInTheDocument();
    expect(mockedCompany.summary).not.toHaveBeenCalled();
  });

  it("redirects a signed-out visitor to /login", async () => {
    mockedApi.me.mockRejectedValue(new ApiError(401, "Not authenticated"));
    render(
      <ReviewLayout>
        <p>page content</p>
      </ReviewLayout>,
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
