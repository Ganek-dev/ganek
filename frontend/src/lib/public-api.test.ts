import { afterEach, describe, expect, it, vi } from "vitest";

// the module is server-only; the guard package throws under jsdom
vi.mock("server-only", () => ({}));

import { publicApi, resolveJobView, type PublicJobDetail } from "./public-api";

const job = { slug: "draft-role", title: "Draft Role" } as PublicJobDetail;

describe("resolveJobView", () => {
  it("fetches once and never previews without a token", async () => {
    const fetchJob = vi.fn().mockResolvedValue(job);
    await expect(resolveJobView(fetchJob)).resolves.toEqual({ job, previewing: false });
    expect(fetchJob).toHaveBeenCalledTimes(1);
    expect(fetchJob).toHaveBeenCalledWith(undefined);
  });

  it("treats a live job opened with a token as the live page", async () => {
    const fetchJob = vi.fn().mockResolvedValue(job);
    await expect(resolveJobView(fetchJob, "tok")).resolves.toEqual({ job, previewing: false });
  });

  it("previews only when the plain lookup would 404", async () => {
    const fetchJob = vi.fn((preview?: string) => Promise.resolve(preview ? job : null));
    await expect(resolveJobView(fetchJob, "tok")).resolves.toEqual({ job, previewing: true });
  });

  it("returns no job when the token is wrong or expired", async () => {
    const fetchJob = vi.fn().mockResolvedValue(null);
    await expect(resolveJobView(fetchJob, "bad")).resolves.toEqual({ job: null, previewing: false });
    expect(fetchJob).toHaveBeenCalledTimes(1);
  });
});

describe("publicApi job fetch headers", () => {
  const ok = { ok: true, status: 200, json: () => Promise.resolve(job) };

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the view headers when the page says the load counts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok);
    vi.stubGlobal("fetch", fetchMock);
    await publicApi.singleCompanyJob("draft-role", undefined, {
      "X-Ganek-View": "1",
      "X-Ganek-Source": "direct",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/public\/company\/jobs\/draft-role$/);
    expect(init.cache).toBe("no-store");
    expect(init.headers).toEqual({ "X-Ganek-View": "1", "X-Ganek-Source": "direct" });
  });

  it("sends no view header by default (metadata, previews)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok);
    vi.stubGlobal("fetch", fetchMock);
    await publicApi.companyJob("acme", "draft-role", "tok");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/public\/companies\/acme\/jobs\/draft-role\?preview=tok$/);
    expect(init.headers ?? {}).not.toHaveProperty("X-Ganek-View");
  });
});
