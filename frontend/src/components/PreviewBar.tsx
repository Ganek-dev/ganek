import { Eye } from "lucide-react";

/** Strip over a public job page opened through a recruiter's preview link
 * (spec job posts v2 5.3): the job is not published, the page is not
 * indexed, nobody can apply from it. Brand tone like the demo banner so it
 * follows the company theme. Server-rendered markup, no script. */
export function PreviewBar() {
  return (
    <div
      role="status"
      data-testid="preview-bar"
      className="flex items-center justify-center gap-2 bg-brand px-4 py-2 text-[12.5px] text-brand-foreground"
      style={{ filter: "brightness(0.92)" }}
    >
      <Eye aria-hidden className="h-[15px] w-[15px] shrink-0" />
      <span>
        <b className="font-semibold">Preview, not live.</b> Candidates cannot see this page until
        the job is published.
      </span>
    </div>
  );
}
