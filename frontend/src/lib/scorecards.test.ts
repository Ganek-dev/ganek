import { afterEach, describe, expect, it, vi } from "vitest";

import { RECOMMENDATION_LABELS, scorecards, waitingCopy } from "./api";

describe("waitingCopy", () => {
  it("pluralises days", () => {
    expect(waitingCopy("Jane Doe", 4)).toBe("Waiting on Jane Doe for 4 days");
    expect(waitingCopy("Jane Doe", 1)).toBe("Waiting on Jane Doe for 1 day");
    expect(waitingCopy("Jane Doe", 0)).toBe("Waiting on Jane Doe, requested today");
  });
});

describe("RECOMMENDATION_LABELS", () => {
  it("uses the spec labels", () => {
    expect(RECOMMENDATION_LABELS).toEqual({
      strong_no: "Strong no",
      no: "No",
      yes: "Yes",
      strong_yes: "Strong yes",
    });
  });
});

describe("scorecards client", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stub() {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("hits the real routes", async () => {
    const f = stub();
    await scorecards.mine();
    await scorecards.mine("all");
    await scorecards.list("app1");
    await scorecards.requestFrom("app1", "u1");
    await scorecards.dismiss("sc1");
    await scorecards.submit("app1", { ratings: { a: 3 }, recommendation: "yes", comment: null });
    await scorecards.decline("app1");
    const calls = f.mock.calls.map(([url, init]) => [url, (init as RequestInit | undefined)?.method ?? "GET"]);
    expect(calls).toEqual([
      ["/api/v1/scorecards/mine?state=open", "GET"],
      ["/api/v1/scorecards/mine?state=all", "GET"],
      ["/api/v1/scorecards/applications/app1", "GET"],
      ["/api/v1/scorecards/applications/app1", "POST"],
      ["/api/v1/scorecards/sc1/dismiss", "POST"],
      ["/api/v1/scorecards/applications/app1/mine", "PUT"],
      ["/api/v1/scorecards/applications/app1/mine/decline", "POST"],
    ]);
    expect(JSON.parse((f.mock.calls[3]![1] as RequestInit).body as string)).toEqual({ reviewer_user_id: "u1" });
  });
});
