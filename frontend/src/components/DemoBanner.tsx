import { FlaskConical } from "lucide-react";

/** Strip shown on every admin and public page of a demo instance (the
 * backend reports `demo: true` on /auth/providers). Candidate pages use the
 * brand variant so the strip follows the company theme; the admin shell uses
 * the neutral one. Never rendered on the quiz screen: that layout must not
 * shift mid-question. */
export function DemoBanner({ tone = "admin" }: { tone?: "admin" | "brand" }) {
  const brand = tone === "brand";
  return (
    <div
      role="status"
      data-testid="demo-banner"
      className={
        brand
          ? "flex items-center justify-center gap-2 bg-brand px-4 py-2 text-[12.5px] text-brand-foreground"
          : "mb-5 flex items-center gap-2 rounded-md border border-edge bg-muted-fill/40 px-4 py-2.5 text-[13px] text-g700"
      }
      style={brand ? { filter: "brightness(0.92)" } : undefined}
    >
      <FlaskConical aria-hidden className="h-[15px] w-[15px] shrink-0" />
      <span>
        <b className="font-semibold">Demo workspace.</b> Fictional data, resets nightly.
        {brand ? " Nothing you type or upload here is kept." : ""}
      </span>
    </div>
  );
}
