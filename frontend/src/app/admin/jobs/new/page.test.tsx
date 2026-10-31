import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, questionnaires, questions, type JobOut } from "@/lib/api";

import NewJobPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, jobs: { ...original.api.jobs, create: vi.fn() } },
    companyApi: {
      ...original.companyApi,
      summary: vi.fn().mockResolvedValue({
        slug: "acme",
        name: "Acme",
        mode: "single",
        screening_questions: [],
      }),
    },
    questionnaires: { ...original.questionnaires, list: vi.fn() },
    questions: { ...original.questions, resolve: vi.fn() },
  };
});

describe("NewJobPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(questionnaires.list).mockResolvedValue([]);
    vi.mocked(questions.resolve).mockResolvedValue([]);
  });

  it("opens the new job's overview after creating it", async () => {
    vi.mocked(api.jobs.create).mockResolvedValue({ id: "abc" } as JobOut);
    render(<NewJobPage />);
    await userEvent.type(await screen.findByLabelText("Job title"), "Platform Engineer");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));
    expect(api.jobs.create).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Platform Engineer" }),
    );
    expect(push).toHaveBeenCalledWith("/admin/jobs/abc");
  });
});
