import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, applications, type AccessEntry } from "@/lib/api";

import { AccessTrailCard } from "./AccessTrailCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    applications: { ...original.applications, accessLog: vi.fn() },
  };
});

const mocked = vi.mocked(applications);
const NOW = new Date("2026-10-24T12:00:00Z");

function entry(overrides: Partial<AccessEntry>): AccessEntry {
  return {
    id: "e1",
    action: "view",
    actor_email: "erika@acme.example",
    actor_label: "Erika",
    api_key_name: null,
    created_at: "2026-10-24T11:00:00Z",
    ...overrides,
  };
}

describe("AccessTrailCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders nothing while nobody has looked yet", async () => {
    mocked.accessLog.mockResolvedValue([]);
    const { container } = render(<AccessTrailCard applicationId="a1" now={NOW} />);
    await vi.waitFor(() => expect(mocked.accessLog).toHaveBeenCalledWith("a1"));
    expect(container).toBeEmptyDOMElement();
  });

  it("lists who looked, what they opened and when", async () => {
    mocked.accessLog.mockResolvedValue([
      entry({ id: "e1", action: "dsar_export", created_at: "2026-10-24T11:55:00Z" }),
      entry({ id: "e2", action: "cv_download", actor_label: "Jonas", actor_email: "jonas@acme.example" }),
      entry({ id: "e3", action: "view", actor_email: null, actor_label: null, api_key_name: "ATS sync" }),
    ]);
    render(<AccessTrailCard applicationId="a1" now={NOW} />);
    expect(await screen.findByText("Access")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Erika exported the data bundle");
    expect(items[0]).toHaveTextContent("5m ago");
    expect(items[1]).toHaveTextContent("Jonas opened the CV");
    expect(items[2]).toHaveTextContent("API key ATS sync opened the profile");
    expect(items[2]).toHaveTextContent("1h ago");
  });

  it("stays hidden for a member (403)", async () => {
    mocked.accessLog.mockRejectedValue(new ApiError(403, "Admin role required"));
    const { container } = render(<AccessTrailCard applicationId="a1" now={NOW} />);
    await vi.waitFor(() => expect(mocked.accessLog).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
