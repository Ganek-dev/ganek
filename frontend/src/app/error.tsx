"use client";

import { Wordmark } from "@/components/Wordmark";

/** Styled catch-all for uncaught render errors (M5.7 H4) — replaces Next's
 * unbranded default. Client component by contract; receives reset() to
 * re-render the segment. */
export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <div className="max-w-[380px] text-center">
        <Wordmark className="text-[20px]" />
        <h1 className="mt-5 font-heading text-[25px] leading-[1.2] font-semibold">
          Something broke
        </h1>
        <p className="mt-2.5 text-[14.5px] leading-[22px] text-g600 [text-wrap:pretty]">
          The page hit an unexpected error. It&apos;s been nothing you did — try again,
          and if it keeps happening the instance logs will say why.
        </p>
        <div className="mt-[22px] flex items-center justify-center">
          <button
            type="button"
            onClick={reset}
            className="inline-flex h-10 items-center rounded-md border-[1.5px] border-edge px-[18px] text-[13.5px] font-semibold hover:border-accent hover:text-accent"
          >
            Try again
          </button>
        </div>
      </div>
    </main>
  );
}
