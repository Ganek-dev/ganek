import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clockOffsetMs, useCountdownMs } from "./use-countdown";

const START = new Date("2026-10-29T10:00:00.000Z").getTime();

describe("useCountdownMs", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(START);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts down from an absolute deadline on every tick", () => {
    const deadline = new Date(START + 15_000).toISOString();
    const { result } = renderHook(() => useCountdownMs(deadline));
    expect(result.current).toBe(15_000);
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(result.current).toBe(14_000);
  });

  it("returns null without a deadline", () => {
    const { result } = renderHook(() => useCountdownMs(null));
    expect(result.current).toBeNull();
  });

  it("corrects for a server clock that runs ahead of the client", () => {
    const serverNow = new Date(START + 30_000).toISOString();
    const deadline = new Date(START + 30_000 + 15_000).toISOString();
    const { result } = renderHook(() => useCountdownMs(deadline, clockOffsetMs(serverNow)));
    // uncorrected this would read 45 s; the server only granted 15
    expect(result.current).toBe(15_000);
  });

  it("corrects for a server clock that runs behind the client", () => {
    const serverNow = new Date(START - 30_000).toISOString();
    const deadline = new Date(START - 30_000 + 15_000).toISOString();
    const { result } = renderHook(() => useCountdownMs(deadline, clockOffsetMs(serverNow)));
    // uncorrected this would already read 0:00 and auto-advance
    expect(result.current).toBe(15_000);
  });

  it("never shows more than the question's limit", () => {
    const deadline = new Date(START + 22_000).toISOString();
    const { result } = renderHook(() => useCountdownMs(deadline, 0, 20_000));
    expect(result.current).toBe(20_000);
  });

  it("resyncs when a throttled tab becomes visible past the deadline", () => {
    const deadline = new Date(START + 15_000).toISOString();
    const { result } = renderHook(() => useCountdownMs(deadline));
    // a hidden tab stops firing the interval; only the wall clock moves on
    vi.setSystemTime(START + 20_000);
    expect(result.current).toBe(15_000);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(result.current).toBe(0);
  });

  it("resyncs on window focus after a sleep", () => {
    const deadline = new Date(START + 15_000).toISOString();
    const { result } = renderHook(() => useCountdownMs(deadline));
    vi.setSystemTime(START + 9_000);
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(result.current).toBe(6_000);
  });

  it("stops listening after unmount", () => {
    const deadline = new Date(START + 15_000).toISOString();
    const remove = vi.spyOn(document, "removeEventListener");
    const { unmount } = renderHook(() => useCountdownMs(deadline));
    unmount();
    expect(remove).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
  });
});

describe("clockOffsetMs", () => {
  it("is client time minus server time", () => {
    expect(clockOffsetMs("2026-10-29T10:00:00.000Z", START + 2_500)).toBe(2_500);
    expect(clockOffsetMs("2026-10-29T10:00:05.000Z", START)).toBe(-5_000);
  });

  it("falls back to the client clock when the stamp is missing or unreadable", () => {
    expect(clockOffsetMs(undefined, START)).toBe(0);
    expect(clockOffsetMs(null, START)).toBe(0);
    expect(clockOffsetMs("not a date", START)).toBe(0);
  });
});
