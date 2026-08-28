/** "ganek." wordmark — logo direction 8d from the design handoff.
 *  Pure type: Space Grotesk 600, the "g" and "." in the ganek accent.
 *  On dark constant surfaces (sidebar) pass `accentClassName="text-accent-soft"`. */
export function Wordmark({
  className = "",
  accentClassName = "text-accent",
}: {
  className?: string;
  accentClassName?: string;
}) {
  return (
    <span className={`font-heading font-semibold tracking-tight ${className}`.trim()}>
      <span className={accentClassName}>g</span>
      <span>anek</span>
      <span className={accentClassName}>.</span>
    </span>
  );
}
