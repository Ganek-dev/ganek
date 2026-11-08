/** Days left in the 14-day Team trial (card B1d), rounded up so the last
 * afternoon still reads "1 day left"; 0 once it is over. */
export function trialDaysLeft(endsAt: string, now: number = Date.now()): number {
  const left = new Date(endsAt).getTime() - now;
  if (!Number.isFinite(left) || left <= 0) return 0;
  return Math.ceil(left / 86_400_000);
}

export function trialDaysText(days: number): string {
  return `${days} ${days === 1 ? "day" : "days"} left`;
}
