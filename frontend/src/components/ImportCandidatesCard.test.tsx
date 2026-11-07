import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, type JobOut } from "@/lib/api";

import { ImportCandidatesCard } from "./ImportCandidatesCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      jobs: { ...original.api.jobs, importCandidates: vi.fn() },
    },
  };
});

const importCandidates = vi.mocked(api.jobs.importCandidates);

function job(status: JobOut["status"] = "published"): JobOut {
  return { id: "job-1", title: "Backend Engineer", status } as JobOut;
}

function upload(text: string) {
  const file = new File([text], "people.csv", { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("CSV file"), {
    target: { files: [file] },
  });
}

const CSV =
  "First Name,Last Name,Email\nAda,Lovelace,ada@x.dev\nBob,Builder,bob@x.dev\n";

describe("ImportCandidatesCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks to publish first on an unpublished job", () => {
    render(<ImportCandidatesCard job={job("draft")} onImported={() => {}} />);
    expect(
      screen.getByText("Publish the job to import candidates."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("CSV file")).not.toBeInTheDocument();
  });

  it("maps, checks with a dry run, then imports", async () => {
    const onImported = vi.fn();
    importCandidates.mockResolvedValueOnce({
      imported: 1,
      duplicates: 1,
      invalid: 0,
      duplicate_rows: [2],
      invalid_rows: [],
      dry_run: true,
    });
    importCandidates.mockResolvedValueOnce({
      imported: 1,
      duplicates: 1,
      invalid: 0,
      duplicate_rows: [2],
      invalid_rows: [],
      dry_run: false,
    });
    render(<ImportCandidatesCard job={job()} onImported={onImported} />);
    upload(CSV);
    expect(await screen.findByText("people.csv · 2 rows")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue("2");
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();

    const checkButton = screen.getByRole("button", { name: "Check file" });
    expect(checkButton).toBeDisabled(); // the origin is required
    fireEvent.change(screen.getByPlaceholderText("our Personio account"), {
      target: { value: "our Personio account" },
    });
    fireEvent.click(checkButton);
    expect(
      await screen.findByText(
        /already in this workspace or repeated \(rows 2\)/,
      ),
    ).toBeInTheDocument();
    expect(importCandidates).toHaveBeenLastCalledWith("job-1", {
      rows: [
        { name: "Ada Lovelace", email: "ada@x.dev", source: null },
        { name: "Bob Builder", email: "bob@x.dev", source: null },
      ],
      origin: "our Personio account",
      dry_run: true,
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Import 1 candidate and send invites",
      }),
    );
    expect(
      await screen.findByText(/Imported 1 candidate, skipped 1/),
    ).toBeInTheDocument();
    expect(importCandidates).toHaveBeenLastCalledWith(
      "job-1",
      expect.objectContaining({ dry_run: false }),
    );
    expect(onImported).toHaveBeenCalledOnce();
  });

  it("drops the check when the mapping changes", async () => {
    importCandidates.mockResolvedValueOnce({
      imported: 2,
      duplicates: 0,
      invalid: 0,
      duplicate_rows: [],
      invalid_rows: [],
      dry_run: true,
    });
    render(<ImportCandidatesCard job={job()} onImported={() => {}} />);
    upload(CSV);
    await screen.findByText("people.csv · 2 rows");
    fireEvent.change(screen.getByPlaceholderText("our Personio account"), {
      target: { value: "a spreadsheet" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check file" }));
    await screen.findByRole("button", {
      name: "Import 2 candidates and send invites",
    });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "" } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Check file" })).toBeDisabled(),
    );
    expect(screen.getByText(/Pick the email column/)).toBeInTheDocument();
  });

  it("refuses an empty file", async () => {
    render(<ImportCandidatesCard job={job()} onImported={() => {}} />);
    upload("name,email\n");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "no rows below the header",
    );
  });
});
