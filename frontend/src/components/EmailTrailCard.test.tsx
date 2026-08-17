import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { applications, type EmailDelivery } from "@/lib/api";

import { EmailTrailCard } from "./EmailTrailCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    applications: { ...original.applications, emails: vi.fn() },
  };
});

const mocked = vi.mocked(applications);

function row(overrides: Partial<EmailDelivery> = {}): EmailDelivery {
  return {
    id: crypto.randomUUID(),
    kind: "quiz_invite",
    status: "sent",
    attempts: 1,
    last_error: null,
    created_at: new Date().toISOString(),
    sent_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("EmailTrailCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing while the trail is empty", async () => {
    mocked.emails.mockResolvedValue([]);
    const { container } = render(<EmailTrailCard applicationId="a1" />);
    await vi.waitFor(() => expect(mocked.emails).toHaveBeenCalledWith("a1"));
    expect(container).toBeEmptyDOMElement();
  });

  it("lists deliveries with readable labels", async () => {
    mocked.emails.mockResolvedValue([
      row({ kind: "quiz_invite" }),
      row({ kind: "rejection", status: "queued", attempts: 0, sent_at: null }),
    ]);
    render(<EmailTrailCard applicationId="a1" />);
    expect(await screen.findByText("Assessment invite")).toBeInTheDocument();
    expect(screen.getByText("Rejection")).toBeInTheDocument();
    expect(screen.getByText("queued")).toBeInTheDocument();
    expect(screen.queryByText(/failed/)).not.toBeInTheDocument();
  });

  it("surfaces failures with the SMTP hint", async () => {
    mocked.emails.mockResolvedValue([
      row({ kind: "quiz_invite", status: "failed", sent_at: null, last_error: "boom" }),
    ]);
    render(<EmailTrailCard applicationId="a1" />);
    expect(await screen.findByText("1 failed")).toBeInTheDocument();
    expect(screen.getByText(/check your SMTP settings/)).toBeInTheDocument();
  });

  it("names the unconfigured-SMTP case explicitly", async () => {
    mocked.emails.mockResolvedValue([
      row({ status: "failed", sent_at: null, last_error: "SMTP not configured" }),
    ]);
    render(<EmailTrailCard applicationId="a1" />);
    expect(
      await screen.findByText(/Email is not configured on this instance/),
    ).toBeInTheDocument();
  });
});
