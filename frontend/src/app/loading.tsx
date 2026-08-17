/** Route-transition skeleton (M5.7 H4): a quiet centered pulse instead of
 * a blank white flash. Segment-level loading states stay where they are —
 * this only covers routes without their own. */
export default function Loading() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background">
      <div aria-busy="true" className="h-6 w-32 animate-pulse rounded-md bg-muted-fill" />
    </main>
  );
}
