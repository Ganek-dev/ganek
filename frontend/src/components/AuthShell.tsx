import { Wordmark } from "@/components/Wordmark";

/** Centered 360px auth column from handoff screen 13. Used by login,
 * signup and reset — anything the wordmark should crown. */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="flex w-[360px] flex-col items-center">
        <Wordmark className="text-[22px]" />
        <h1 className="mt-6 text-center font-heading text-2xl font-semibold tracking-[-0.01em]">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-2.5 text-center text-sm leading-[21px] text-g500">{subtitle}</p>
        ) : null}
        <div className="mt-6 flex w-full flex-col gap-3.5">{children}</div>
        {footer ? <div className="mt-5 text-[13.5px] text-g500">{footer}</div> : null}
      </div>
    </main>
  );
}
