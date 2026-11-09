import { KeyRound } from "lucide-react";

/** "Continue with <name>" for the instance's OpenID Connect provider. A
 * plain link, like GoogleButton: the backend drives the redirect dance. */
export function SsoButton({ name, href }: { name: string; href: string }) {
  return (
    <a
      href={href}
      className="inline-flex h-10 w-full items-center justify-center gap-2.5 rounded-md border-[1.5px] border-edge bg-surface text-sm font-medium hover:bg-muted-fill"
    >
      <KeyRound aria-hidden className="h-4 w-4" />
      Continue with {name}
    </a>
  );
}
