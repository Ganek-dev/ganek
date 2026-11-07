import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, applications, clearSharedGets, companyApi, stats } from "./api";

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
      new ApiError(409, "Email already registered", "Email already registered"),
    );
  });

  it("surfaces the first message of a validation-error list, not the status text", async () => {
    // FastAPI 422 shape - the setup form used to show "Unprocessable Content"
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
      new ApiError(422, "value is not a valid email address: reserved name", [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address: reserved name",
        },
      ]),
    );
  });

  it("keeps the status text for unrecognized error bodies", async () => {
    mockFetch(422, { detail: { odd: "shape" } });
    await expect(api.me()).rejects.toThrowError(
      new ApiError(422, "Unprocessable Content", { odd: "shape" }),
    );
  });
});

describe("401 interceptor", () => {
  const realLocation = window.location;

  afterEach(() => {
    vi.unstubAllGlobals();
    Object.defineProperty(window, "location", { value: realLocation, writable: true });
  });

  function stubLocation(pathname: string) {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...realLocation, pathname, assign },
      writable: true,
    });
    return assign;
  }

  it("bounces an expired admin session to /login", async () => {
    const assign = stubLocation("/admin/applicants");
    mockFetch(401, { detail: "Not authenticated" });
    await expect(api.me()).rejects.toThrowError(
      new ApiError(401, "Not authenticated", "Not authenticated"),
    );
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("leaves non-admin surfaces alone - a failed login is not a redirect", async () => {
    const assign = stubLocation("/login");
    mockFetch(401, { detail: "Invalid email or password" });
    await expect(
      api.login({ email: "a@b.c", password: "wrong-but-long" }),
    ).rejects.toThrowError(
      new ApiError(401, "Invalid email or password", "Invalid email or password"),
    );
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("applications query params", () => {
  it("serialises every list filter and the export selection", () => {
    const url = applications.exportUrl("csv", {
      job_id: "job-1",
      stage: "new",
      q: "a b",
      score_min: 60,
      quiz: "completed",
      source: "linkedin",
      flagged: false,
      since_days: 30,
      ids: ["1", "2"],
    });
    const params = new URL(url, "http://x").searchParams;
    expect(params.get("format")).toBe("csv");
    expect(params.get("q")).toBe("a b");
    expect(params.get("score_min")).toBe("60");
    expect(params.get("quiz")).toBe("completed");
    expect(params.get("source")).toBe("linkedin");
    expect(params.get("flagged")).toBe("false");
    expect(params.get("since_days")).toBe("30");
    expect(params.get("ids")).toBe("1,2");
    expect(url).toContain("ids=1%2C2");
  });

  it("leaves unset filters out of the query", () => {
    expect(applications.exportUrl("json")).toBe("/api/v1/applications/export?format=json");
  });
});

describe("shared session reads (hard-load dedupe)", () => {
  function okFetch() {
    const fetchMock = vi.fn().mockImplementation(
      () =>
        Promise.resolve(
          new Response(JSON.stringify({ id: "u1", role: "admin" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  afterEach(() => {
    clearSharedGets();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("fires one request for concurrent and just-settled callers", async () => {
    const fetchMock = okFetch();
    await Promise.all([api.me(), api.me(), api.me()]);
    await api.me();
    await Promise.all([companyApi.get(), companyApi.get(), companyApi.get()]);
    await Promise.all([stats.overview(), stats.overview()]);
    await Promise.all([api.providers(), api.providers()]);
    const paths = fetchMock.mock.calls.map(([path]) => path as string);
    expect(paths).toEqual([
      "/api/v1/auth/me",
      "/api/v1/company",
      "/api/v1/stats/overview",
      "/api/v1/auth/providers",
    ]);
  });

  it("refetches once the short window has passed", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const fetchMock = okFetch();
    await api.me();
    vi.setSystemTime(Date.now() + 6_000);
    await api.me();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never keeps a failure", async () => {
    mockFetch(503, { detail: "down" }, "Service Unavailable");
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    const fetchMock = okFetch();
    await expect(api.me()).resolves.toMatchObject({ id: "u1" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("drops memoized reads after any write", async () => {
    const fetchMock = okFetch();
    await api.me();
    await api.updateProfile("Max");
    await api.me();
    const paths = fetchMock.mock.calls.map(([path]) => path as string);
    expect(paths).toEqual(["/api/v1/auth/me", "/api/v1/users/me", "/api/v1/auth/me"]);
  });

  it("leaves uncached reads alone", async () => {
    const fetchMock = okFetch();
    await Promise.all([api.availability.get(), api.availability.get()]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
