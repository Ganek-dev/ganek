import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, notes, type Note, type UserOut } from "@/lib/api";

import { NotesCard } from "./NotesCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: { ...original.api, me: vi.fn() },
    notes: { list: vi.fn(), add: vi.fn(), remove: vi.fn() },
  };
});

const mockedApi = vi.mocked(api);
const mockedNotes = vi.mocked(notes);

function user(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: "u1",
    company_id: "co1",
    email: "dana@acme.dev",
    role: "member",
    has_password: true,
    ...overrides,
  };
}

function note(overrides: Partial<Note> = {}): Note {
  return {
    id: "n1",
    body: "Strong React answers, weak on SQL.",
    author_email: "dana@acme.dev",
    created_at: "2026-08-09T10:00:00Z",
    ...overrides,
  };
}

describe("NotesCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.me.mockResolvedValue(user());
    mockedNotes.list.mockResolvedValue([]);
    mockedNotes.add.mockResolvedValue(note());
    mockedNotes.remove.mockResolvedValue(undefined);
  });

  it("lists notes chronologically with authors and relative time", async () => {
    mockedNotes.list.mockResolvedValue([
      note({ id: "n1", body: "First note", author_email: "dana@acme.dev" }),
      note({ id: "n2", body: "Second note", author_email: "sam@acme.dev" }),
    ]);
    render(<NotesCard applicationId="app1" />);

    const first = await screen.findByText("First note");
    const second = await screen.findByText("Second note");
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/dana/)).toBeInTheDocument();
    expect(screen.getByText(/sam/)).toBeInTheDocument();
  });

  it("shows 'former teammate' for a null author", async () => {
    mockedNotes.list.mockResolvedValue([note({ author_email: null })]);
    render(<NotesCard applicationId="app1" />);

    expect(await screen.findByText(/former teammate/)).toBeInTheDocument();
  });

  it("adds a note via the input (Enter and button) and clears it", async () => {
    mockedNotes.add.mockResolvedValueOnce(note({ id: "n1", body: "typed text" }));
    render(<NotesCard applicationId="app1" />);
    const input = await screen.findByPlaceholderText("Add a note for the team…");

    await userEvent.type(input, "typed text");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(mockedNotes.add).toHaveBeenCalledWith("app1", "typed text"));
    await waitFor(() => expect(input).toHaveValue(""));

    mockedNotes.add.mockClear();
    mockedNotes.add.mockResolvedValueOnce(note({ id: "n2", body: "second entry" }));
    await userEvent.type(input, "second entry");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(mockedNotes.add).toHaveBeenCalledWith("app1", "second entry"));
  });

  it("shows delete only on own notes for members, on all for admins", async () => {
    mockedNotes.list.mockResolvedValue([
      note({ id: "n1", body: "First note", author_email: "dana@acme.dev" }),
      note({ id: "n2", body: "Second note", author_email: "sam@acme.dev" }),
    ]);
    mockedApi.me.mockResolvedValue(user({ email: "dana@acme.dev", role: "member" }));
    render(<NotesCard applicationId="app1" />);

    await screen.findByText("First note");
    expect(screen.getAllByRole("button", { name: "Delete note" })).toHaveLength(1);
  });

  it("shows delete on all notes for admins", async () => {
    mockedNotes.list.mockResolvedValue([
      note({ id: "n1", body: "First note", author_email: "dana@acme.dev" }),
      note({ id: "n2", body: "Second note", author_email: "sam@acme.dev" }),
    ]);
    mockedApi.me.mockResolvedValue(user({ email: "dana@acme.dev", role: "admin" }));
    render(<NotesCard applicationId="app1" />);

    await screen.findByText("First note");
    await screen.findByText("Second note");
    expect(screen.getAllByRole("button", { name: "Delete note" })).toHaveLength(2);
  });

  it("deletes after confirm and refreshes the list", async () => {
    mockedNotes.list.mockResolvedValue([note({ id: "n1", author_email: "dana@acme.dev" })]);
    mockedApi.me.mockResolvedValue(user({ email: "dana@acme.dev", role: "member" }));
    render(<NotesCard applicationId="app1" />);

    await userEvent.click(await screen.findByRole("button", { name: "Delete note" }));
    expect(mockedNotes.remove).not.toHaveBeenCalled();
    expect(await screen.findByText("Delete?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(mockedNotes.remove).toHaveBeenCalledWith("app1", "n1"));
    await waitFor(() =>
      expect(screen.queryByText("Strong React answers, weak on SQL.")).not.toBeInTheDocument(),
    );
  });

  it("cancels the delete confirmation on No", async () => {
    mockedNotes.list.mockResolvedValue([note({ id: "n1", author_email: "dana@acme.dev" })]);
    mockedApi.me.mockResolvedValue(user({ email: "dana@acme.dev", role: "member" }));
    render(<NotesCard applicationId="app1" />);

    await userEvent.click(await screen.findByRole("button", { name: "Delete note" }));
    await userEvent.click(await screen.findByRole("button", { name: "No" }));
    expect(mockedNotes.remove).not.toHaveBeenCalled();
    expect(screen.getByText("Strong React answers, weak on SQL.")).toBeInTheDocument();
  });

  it("shows the count badge and empty state with just the input", async () => {
    mockedNotes.list.mockResolvedValue([]);
    render(<NotesCard applicationId="app1" />);

    expect(await screen.findByText("Notes")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Add a note for the team…")).toBeInTheDocument();
  });

  it("shows an error alert when adding fails", async () => {
    mockedNotes.add.mockRejectedValue(new Error("Note body is required"));
    render(<NotesCard applicationId="app1" />);
    const input = await screen.findByPlaceholderText("Add a note for the team…");

    await userEvent.type(input, "oops{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Note body is required");
  });
});
