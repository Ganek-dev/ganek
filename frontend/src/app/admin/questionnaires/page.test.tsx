import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { questionnaires, type QuestionnaireOut } from "@/lib/api";

import QuestionnairesIndexPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    questionnaires: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn() },
  };
});

const mocked = vi.mocked(questionnaires);

function makeRow(overrides: Partial<QuestionnaireOut>): QuestionnaireOut {
  return {
    id: "q1",
    name: "Frontend basics v2",
    description: "12-question sweep across HTML, CSS and React.",
    shuffle: false,
    question_refs: ["a", "b", "c"],
    created_at: "2026-07-25T10:00:00Z",
    updated_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    ...overrides,
  };
}

describe("QuestionnairesIndexPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.list.mockResolvedValue([makeRow({})]);
    mocked.create.mockResolvedValue(makeRow({ id: "new-q", name: "Untitled" }));
  });

  it("lists questionnaires with name, ref count and relative updated time", async () => {
    render(<QuestionnairesIndexPage />);
    expect(await screen.findByText("Frontend basics v2")).toBeInTheDocument();
    expect(screen.getByText(/12-question sweep/)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // question ref count
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
  });

  it("shows an empty-state CTA when there are no questionnaires", async () => {
    mocked.list.mockResolvedValue([]);
    render(<QuestionnairesIndexPage />);
    expect(await screen.findByText(/No questionnaires yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create the first" })).toBeInTheDocument();
  });

  it("creates an empty questionnaire and routes to its builder", async () => {
    render(<QuestionnairesIndexPage />);
    await screen.findByText("Frontend basics v2");
    await userEvent.click(screen.getByRole("button", { name: /New questionnaire/ }));
    await waitFor(() => expect(mocked.create).toHaveBeenCalledTimes(1));
    expect(mocked.create.mock.calls[0][0].name).toMatch(/Untitled /);
    expect(push).toHaveBeenCalledWith("/admin/questionnaires/new-q");
  });

  it("surfaces API errors as an alert", async () => {
    mocked.list.mockRejectedValueOnce(new Error("boom"));
    render(<QuestionnairesIndexPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
