import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiKeys } from "@/lib/api";

import { ApiKeysCard } from "./ApiKeysCard";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    apiKeys: { ...original.apiKeys, list: vi.fn() },
  };
});

const mocked = vi.mocked(apiKeys);

describe("ApiKeysCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("tells admins that read keys also fetch CVs", async () => {
    mocked.list.mockResolvedValue([]);
    render(<ApiKeysCard />);
    await vi.waitFor(() => expect(mocked.list).toHaveBeenCalled());
    expect(screen.getByTestId("api-keys-card")).toHaveTextContent(
      "lists applicants, exports and fetches CVs",
    );
  });
});
