import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, accessLogApi, team, type AccessLogRow } from "@/lib/api";

import { AccessLogSection } from "./AccessLogSection";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    accessLogApi: { ...original.accessLogApi, list: vi.fn() }, // exportUrl stays real
    team: { ...original.team, list: vi.fn() },
  };
});

const mocked = vi.mocked(accessLogApi);
const mockedTeam = vi.mocked(team);
const NOW = new Date("2026-10-24T12:00:00Z");

function row(overrides: Partial<AccessLogRow>): AccessLogRow {
  return {
    id: "r1",
    action: "view",
    actor_email: "erika@northwind.example",
    actor_label: "Erika",
    api_key_name: null,
    application_id: "app-1",
    candidate_name: "Tomas Hruby",
    job_title: "Backend Engineer",
    created_at: "2026-10-24T11:00:00Z",
    ...overrides,
  };
}

describe("AccessLogSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedTeam.list.mockResolvedValue([
      { id: "u1", email: "erika@northwind.example", display_label: "Erika", role: "admin" },
      { id: "u2", email: "jonas@northwind.example", display_label: "Jonas", role: "member" },
    ] as never);
  });

  it("says so while nobody has opened a candidate", async () => {
    mocked.list.mockResolvedValue({ items: [], total: 0 });
    render(<AccessLogSection now={NOW} />);
    expect(await screen.findByText("Nobody has opened a candidate yet.")).toBeInTheDocument();
  });

  it("lists who looked at whom, newest first", async () => {
    mocked.list.mockResolvedValue({
      items: [
        row({ id: "r1", action: "cv_download", created_at: "2026-10-24T11:55:00Z" }),
        row({ id: "r2", actor_label: null, actor_email: null, api_key_name: "ATS sync" }),
      ],
      total: 2,
    });
    render(<AccessLogSection now={NOW} />);
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3); // header + 2
    expect(within(rows[1]).getByText("Erika")).toBeInTheDocument();
    expect(within(rows[1]).getByText("opened the CV")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Tomas Hruby")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Backend Engineer")).toBeInTheDocument();
    expect(within(rows[1]).getByText("5m ago")).toBeInTheDocument();
    expect(within(rows[2]).getByText("API key ATS sync")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("filters by teammate and action and keeps the CSV link in step", async () => {
    mocked.list.mockResolvedValue({ items: [row({})], total: 1 });
    render(<AccessLogSection now={NOW} />);
    await screen.findAllByRole("row");
    await userEvent.selectOptions(await screen.findByLabelText("Teammate"), "u2");
    await waitFor(() =>
      expect(mocked.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ actor_user_id: "u2", offset: 0 }),
      ),
    );
    await userEvent.selectOptions(screen.getByLabelText("Action"), "dsar_export");
    await waitFor(() =>
      expect(mocked.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ actor_user_id: "u2", action: "dsar_export", offset: 0 }),
      ),
    );
    const link = screen.getByRole("link", { name: "Download CSV" });
    expect(link).toHaveAttribute(
      "href",
      "/api/v1/access-log/export?format=csv&actor_user_id=u2&action=dsar_export",
    );
    expect(link).toHaveAttribute("download");
  });

  it("loads the next page on Show more", async () => {
    const firstPage = Array.from({ length: 50 }, (_, i) => row({ id: `r${i}` }));
    mocked.list.mockResolvedValue({ items: firstPage, total: 60 });
    render(<AccessLogSection now={NOW} />);
    expect(await screen.findAllByRole("row")).toHaveLength(51);
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() =>
      expect(mocked.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 })),
    );
  });

  it("renders nothing for a member (403)", async () => {
    mocked.list.mockRejectedValue(new ApiError(403, "Admin role required"));
    const { container } = render(<AccessLogSection now={NOW} />);
    await waitFor(() => expect(mocked.list).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
