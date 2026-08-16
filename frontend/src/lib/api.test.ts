import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./api";

function mockFetch(status: number, body: unknown, statusText = "Unprocessable Content") {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        statusText,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

describe("request error mapping", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("surfaces string details as-is", async () => {
    mockFetch(409, { detail: "Email already registered" });
    await expect(api.me()).rejects.toThrowError(
      new ApiError(409, "Email already registered"),
    );
  });

  it("surfaces the first message of a validation-error list, not the status text", async () => {
    // FastAPI 422 shape — the setup form used to show "Unprocessable Content"
    mockFetch(422, {
      detail: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address: reserved name",
        },
      ],
    });
    await expect(api.me()).rejects.toThrowError(
      new ApiError(422, "value is not a valid email address: reserved name"),
    );
  });

  it("keeps the status text for unrecognized error bodies", async () => {
    mockFetch(422, { detail: { odd: "shape" } });
    await expect(api.me()).rejects.toThrowError(
      new ApiError(422, "Unprocessable Content"),
    );
  });
});
