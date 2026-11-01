import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { webhooks, type WebhookEndpoint } from "@/lib/api";

import { WebhooksCard } from "./WebhooksCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    webhooks: { list: vi.fn(), create: vi.fn(), remove: vi.fn(), test: vi.fn() },
  };
});

const mocked = vi.mocked(webhooks);

const hook: WebhookEndpoint = {
  id: "h1",
  name: "Slack",
  url: "https://hooks.slack.com/services/T0/B0/x",
  events: ["application.created", "stage.changed"],
  is_active: true,
  created_at: "2026-10-20T10:00:00Z",
  last_delivery: {
    id: "d1",
    event: "application.created",
    status: "failed",
    attempts: 5,
    last_error: "HTTP 500",
    response_status: 500,
    created_at: "2026-10-23T09:00:00Z",
    delivered_at: null,
  },
};

describe("WebhooksCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.list.mockResolvedValue([hook]);
  });

  it("lists endpoints with their events and last delivery, sends a test, removes", async () => {
    mocked.test.mockResolvedValue({ ...hook.last_delivery!, id: "d2", event: "stage.changed", status: "queued", attempts: 0, last_error: null, response_status: null });
    mocked.remove.mockResolvedValue(undefined);
    render(<WebhooksCard />);
    const row = (await screen.findByText("Slack")).closest("li") as HTMLElement;
    expect(within(row).getByText("https://hooks.slack.com/services/T0/B0/x")).toBeInTheDocument();
    expect(within(row).getByText("application.created")).toBeInTheDocument();
    expect(within(row).getByText(/failed/)).toHaveTextContent("HTTP 500");

    await userEvent.click(within(row).getByRole("button", { name: "Send test to Slack" }));
    await waitFor(() => expect(mocked.test).toHaveBeenCalledWith("h1"));
    expect(await screen.findByText(/sample stage\.changed delivery queued/i)).toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Remove Slack" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove webhook" }));
    await waitFor(() => expect(mocked.remove).toHaveBeenCalledWith("h1"));
  });

  it("keeps the plain test wording for a ping delivery", async () => {
    mocked.test.mockResolvedValue({ ...hook.last_delivery!, id: "d3", event: "ping", status: "queued", attempts: 0, last_error: null, response_status: null });
    render(<WebhooksCard />);
    const row = (await screen.findByText("Slack")).closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Send test to Slack" }));
    expect(await screen.findByText(/test delivery queued/i)).toBeInTheDocument();
  });

  it("creates an endpoint from name, url and events and shows the secret once", async () => {
    mocked.create.mockResolvedValue({
      ...hook,
      id: "h2",
      name: "Zapier",
      url: "https://hooks.zapier.com/x",
      events: ["quiz.completed"],
      last_delivery: null,
      secret: "whsec_SECRETSECRETSECRETSECRET",
    });
    render(<WebhooksCard />);
    await screen.findByText("Slack");
    await userEvent.type(screen.getByLabelText("Webhook name"), "Zapier");
    await userEvent.type(screen.getByLabelText("Endpoint URL"), "https://hooks.zapier.com/x");
    // all three events start checked; keep only quiz.completed
    await userEvent.click(screen.getByLabelText("application.created"));
    await userEvent.click(screen.getByLabelText("stage.changed"));
    await userEvent.click(screen.getByRole("button", { name: "Add webhook" }));

    expect(mocked.create).toHaveBeenCalledWith({
      name: "Zapier",
      url: "https://hooks.zapier.com/x",
      events: ["quiz.completed"],
    });
    expect(await screen.findByText("whsec_SECRETSECRETSECRETSECRET")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy signing secret" })).toBeInTheDocument();
  });

  it("surfaces a rejected URL inline", async () => {
    mocked.create.mockRejectedValueOnce(new Error("Webhook URLs must be https:// and name a host"));
    render(<WebhooksCard />);
    await screen.findByText("Slack");
    await userEvent.type(screen.getByLabelText("Webhook name"), "Local");
    await userEvent.type(screen.getByLabelText("Endpoint URL"), "http://localhost:9/x");
    await userEvent.click(screen.getByRole("button", { name: "Add webhook" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/https/);
  });
});
