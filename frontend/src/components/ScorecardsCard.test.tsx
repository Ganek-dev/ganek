import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, scorecards, team, type Scorecard, type TeamUser, type UserOut } from "@/lib/api";

import { ScorecardsCard } from "./ScorecardsCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, me: vi.fn() },
    scorecards: {
      list: vi.fn(),
      requestFrom: vi.fn(),
      dismiss: vi.fn(),
      submit: vi.fn(),
      decline: vi.fn(),
    },
    team: { ...original.team, list: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);
const mockedCards = vi.mocked(scorecards);
const mockedTeam = vi.mocked(team);

const criteria = [{ id: "c1", label: "Communication", hint: "" }];

function me(): UserOut {
  return { id: "u-me", company_id: "co", email: "me@acme.dev", role: "member", has_password: true };
}

function member(id: string, label: string, active = true): TeamUser {
  return {
    id,
    email: `${id}@acme.dev`,
    display_label: label,
    role: "member",
    is_active: active,
    last_login_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function row(overrides: Partial<Scorecard> = {}): Scorecard {
  return {
    id: "s1",
    application_id: "app1",
    reviewer_user_id: "u-jane",
    reviewer_label: "Jane Doe",
    requested_by_label: "Me",
    interview_id: null,
    requested_at: "2026-10-01T10:00:00Z",
    due_from: "2026-10-01T10:00:00Z",
    submitted_at: null,
    dismissed_at: null,
    declined_at: null,
    state: "open",
    waiting_days: 4,
    criteria,
    ratings: {},
    recommendation: null,
    comment: null,
    edited: false,
    can_edit: false,
    ...overrides,
  };
}

describe("ScorecardsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.me.mockResolvedValue(me());
    mockedCards.list.mockResolvedValue([]);
    mockedCards.requestFrom.mockResolvedValue(row());
    mockedCards.dismiss.mockResolvedValue(undefined);
    mockedCards.submit.mockResolvedValue(row({ state: "submitted" }));
    mockedCards.decline.mockResolvedValue(undefined);
    mockedTeam.list.mockResolvedValue([]);
  });

  it("shows a skeleton, then the heading", async () => {
    render(<ScorecardsCard applicationId="app1" />);
    expect(document.querySelector("[aria-busy='true']")).toBeInTheDocument();
    expect(await screen.findByText("Scorecards")).toBeInTheDocument();
  });

  it.each([
    [0, "Waiting on Jane Doe, requested today"],
    [1, "Waiting on Jane Doe for 1 day"],
    [4, "Waiting on Jane Doe for 4 days"],
  ])("renders waiting copy for %i days", async (days, copy) => {
    mockedCards.list.mockResolvedValue([row({ waiting_days: days })]);
    render(<ScorecardsCard applicationId="app1" />);
    expect(await screen.findByText(copy)).toBeInTheDocument();
  });

  it("dismisses an open row and reloads", async () => {
    mockedCards.list.mockResolvedValueOnce([row()]).mockResolvedValueOnce([]);
    render(<ScorecardsCard applicationId="app1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(mockedCards.dismiss).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(screen.queryByText(/Waiting on/)).not.toBeInTheDocument());
  });

  it("does not list dismissed rows", async () => {
    mockedCards.list.mockResolvedValue([row({ state: "dismissed" })]);
    render(<ScorecardsCard applicationId="app1" />);
    await screen.findByText("Scorecards");
    expect(screen.queryByText("Jane Doe")).not.toBeInTheDocument();
  });

  it("request picker excludes self, open and submitted reviewers and inactive users", async () => {
    mockedCards.list.mockResolvedValue([
      row({ id: "s1", reviewer_user_id: "u-open", reviewer_label: "Opal Open" }),
      row({ id: "s2", reviewer_user_id: "u-done", reviewer_label: "Dan Done", state: "submitted", recommendation: "yes" }),
      row({ id: "s3", reviewer_user_id: "u-dis", reviewer_label: "Di Dismissed", state: "dismissed" }),
    ]);
    mockedTeam.list.mockResolvedValue([
      member("u-me", "Me Myself"),
      member("u-open", "Opal Open"),
      member("u-done", "Dan Done"),
      member("u-dis", "Di Dismissed"),
      member("u-gone", "Gone Gary", false),
      member("u-new", "Nia New"),
    ]);
    render(<ScorecardsCard applicationId="app1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Request" }));
    const select = await screen.findByRole("combobox", { name: "Request a scorecard from" });
    await waitFor(() => expect(within(select).getByRole("option", { name: "Nia New" })).toBeInTheDocument());
    const names = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(names).toEqual(["Choose a teammate", "Di Dismissed", "Nia New"]);

    await userEvent.selectOptions(select, "u-new");
    expect(mockedCards.requestFrom).toHaveBeenCalledWith("app1", "u-new");
  });

  it("shows a request failure inline", async () => {
    mockedTeam.list.mockResolvedValue([member("u-new", "Nia New")]);
    mockedCards.requestFrom.mockRejectedValue(new Error("Already submitted"));
    render(<ScorecardsCard applicationId="app1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Request" }));
    await userEvent.selectOptions(await screen.findByRole("combobox"), "u-new");
    expect(await screen.findByRole("alert")).toHaveTextContent("Already submitted");
  });

  it("renders a submitted row with chip, dots, comment and edited", async () => {
    mockedCards.list.mockResolvedValue([
      row({
        state: "submitted",
        recommendation: "strong_yes",
        comment: "Would hire tomorrow",
        submitted_at: "2026-10-02T10:00:00Z",
        edited: true,
        criteria: [
          { id: "c1", label: "Communication", hint: "" },
          { id: "c2", label: "Craft", hint: "" },
        ],
        ratings: { c1: 3 },
      }),
    ]);
    render(<ScorecardsCard applicationId="app1" />);
    expect(await screen.findByText("Strong yes")).toBeInTheDocument();
    expect(screen.getByText("Would hire tomorrow")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "3 of 4" })).toBeInTheDocument();
    expect(screen.getByText("Not assessed")).toBeInTheDocument();
    expect(screen.getByText(/edited/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("declined row of an active teammate offers Request again", async () => {
    mockedTeam.list.mockResolvedValue([member("u-jane", "Jane Doe")]);
    mockedCards.list.mockResolvedValue([row({ state: "declined" })]);
    render(<ScorecardsCard applicationId="app1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Request again" }));
    expect(mockedCards.requestFrom).toHaveBeenCalledWith("app1", "u-jane");
  });

  it.each([
    ["absent from the team list", []],
    ["inactive", [member("u-jane", "Jane Doe", false)]],
  ])("hides Request again when the reviewer is %s", async (_name, list) => {
    mockedTeam.list.mockResolvedValue(list);
    mockedCards.list.mockResolvedValue([
      row({ state: "declined" }),
      row({
        id: "s2",
        state: "submitted",
        recommendation: "no",
        reviewer_user_id: "u-jane",
      }),
    ]);
    render(<ScorecardsCard applicationId="app1" />);
    expect(await screen.findByText("Declined by Jane Doe")).toBeInTheDocument();
    await waitFor(() => expect(mockedTeam.list).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Request again" })).not.toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
  });

  it("hides Request again when the team list fails to load", async () => {
    mockedTeam.list.mockRejectedValue(new Error("nope"));
    mockedCards.list.mockResolvedValue([row({ state: "declined" })]);
    render(<ScorecardsCard applicationId="app1" />);
    expect(await screen.findByText("Declined by Jane Doe")).toBeInTheDocument();
    await waitFor(() => expect(mockedTeam.list).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Request again" })).not.toBeInTheDocument();
  });

  it("renders the inline form for the user's own open row and submits it", async () => {
    mockedCards.list.mockResolvedValue([row({ reviewer_user_id: "u-me", reviewer_label: "Me" })]);
    render(<ScorecardsCard applicationId="app1" autoOpen />);
    expect(await screen.findByRole("radiogroup", { name: "Communication" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yes" }));
    await userEvent.click(screen.getByRole("button", { name: "Submit scorecard" }));
    expect(mockedCards.submit).toHaveBeenCalledWith("app1", {
      ratings: {},
      recommendation: "yes",
      comment: null,
    });
  });

  it("declines from the inline form", async () => {
    mockedCards.list.mockResolvedValue([row({ reviewer_user_id: "u-me", reviewer_label: "Me" })]);
    render(<ScorecardsCard applicationId="app1" />);
    await userEvent.click(await screen.findByText("I did not assess this candidate"));
    expect(mockedCards.decline).toHaveBeenCalledWith("app1");
  });

  it("swaps a submitted own row to the form with Edit when can_edit", async () => {
    mockedCards.list.mockResolvedValue([
      row({
        reviewer_user_id: "u-me",
        reviewer_label: "Me",
        state: "submitted",
        recommendation: "no",
        comment: "meh",
        can_edit: true,
        ratings: { c1: 3 },
        submitted_at: "2026-10-02T10:00:00Z",
      }),
    ]);
    render(<ScorecardsCard applicationId="app1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Comment")).toHaveValue("meh");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(mockedCards.submit).toHaveBeenCalledWith("app1", {
      ratings: { c1: 3 },
      recommendation: "no",
      comment: "meh",
    });
  });

  it("shows a load failure inline", async () => {
    mockedCards.list.mockRejectedValue(new Error("boom"));
    render(<ScorecardsCard applicationId="app1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
