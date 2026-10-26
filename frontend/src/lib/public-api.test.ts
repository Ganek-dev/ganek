import { describe, expect, it, vi } from "vitest";

// the module is server-only; the guard package throws under jsdom
vi.mock("server-only", () => ({}));

import { resolveJobView, type PublicJobDetail } from "./public-api";

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
