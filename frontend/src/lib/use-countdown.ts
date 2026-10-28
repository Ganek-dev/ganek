import { useEffect, useState } from "react";

/** Client-minus-server clock offset for a server-stamped payload.
 *
 * Read it the moment the payload arrives: transit delay only pushes the
 * estimate of the server clock later, so a countdown corrected with it can
 * never show time the server has already spent.
 */
export function clockOffsetMs(
  serverNow: string | null | undefined,
  clientNow: number = Date.now(),
): number {
  const stamp = serverNow ? new Date(serverNow).getTime() : Number.NaN;
  // a backend that predates the stamp (mixed-version upgrade window) gets
  // the uncorrected client clock instead of a NaN ring
  return Number.isNaN(stamp) ? 0 : clientNow - stamp;
}

/** Milliseconds left until an absolute server deadline.
 *
 * Re-derived from the wall clock on every tick, never a decrementing
 * counter, so a laptop that slept or a throttled tab catches up at once.
 * `offsetMs` is the client-minus-server skew from clockOffsetMs; `capMs`
 * bounds the result so a client clock behind the server cannot show more
 * than the question allows. Background tabs throttle timers, so a tab that
 * becomes visible or focused resyncs immediately instead of on the next tick.
 */
export function useCountdownMs(
  deadline: string | null,
  offsetMs = 0,
  capMs?: number,
): number | null {
  // remaining time is derived at render from a ticking clock - no state
  // writes inside effects, and no bogus initial value racing the timer
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const timer = setInterval(tick, 200);
    document.addEventListener("visibilitychange", tick);
    window.addEventListener("focus", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
      window.removeEventListener("focus", tick);
    };
  }, []);
  if (!deadline) return null;
  const remaining = new Date(deadline).getTime() - (now - offsetMs);
  const bounded = capMs === undefined ? remaining : Math.min(remaining, capMs);
  return Math.max(0, bounded);
}
