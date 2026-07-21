import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, applications, type ApplicationOut } from "@/lib/api";

import ApplicantsPage from "./page";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, jobs: { ...original.api.jobs, list: vi.fn() } },
    applications: { list: vi.fn(), setStage: vi.fn(), cvUrl: vi.fn() },
  };
});

const mockedApps = vi.mocked(applications);
const mockedJobs = vi.mocked(api.jobs);

const application: ApplicationOut = {
  id: "app-1",
  job_id: "job-1",
  candidate: {
    id: "cand-1",
    name: "Jane Applicant",
    email: "jane@example.com",
    links: { github: "https://github.com/jane" },
  },
  cv_filename: "jane.pdf",
  cv_size: 250_000,
  message: "Hello!",
  stage: "new",
  source: null,
  created_at: "2026-07-21T10:00:00Z",
};

describe("ApplicantsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApps.list.mockResolvedValue([application]);
    mockedApps.setStage.mockResolvedValue({ ...application, stage: "screening" });
    mockedApps.cvUrl.mockResolvedValue({ download_url: "http://minio.test/cv" });
    mockedJobs.list.mockResolvedValue([
      { id: "job-1", title: "Backend Engineer" } as never,
    ]);
  });

  it("lists applicants with job title, links and CV size", async () => {
    render(<ApplicantsPage />);
    expect(await screen.findByText("Jane Applicant")).toBeInTheDocument();
    expect(screen.getByText(/Backend Engineer · applied/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "github" })).toHaveAttribute(
      "href",
      "https://github.com/jane",
    );
    expect(screen.getByRole("button", { name: /CV \(244 KB\)/ })).toBeInTheDocument();
  });

  it("changes the stage via the dropdown", async () => {
    render(<ApplicantsPage />);
    const select = await screen.findByLabelText("Stage for Jane Applicant");
    await userEvent.selectOptions(select, "screening");
    await waitFor(() =>
      expect(mockedApps.setStage).toHaveBeenCalledWith("app-1", "screening"),
    );
  });

  it("opens the presigned CV url", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ApplicantsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /CV/ }));
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith("http://minio.test/cv", "_blank", "noopener"),
    );
  });
});
