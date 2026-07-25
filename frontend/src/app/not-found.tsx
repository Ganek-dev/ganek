import Link from "next/link";

import { Wordmark } from "@/components/Wordmark";

/** Global 404 (screen 27b): vetd-branded — used when there is no company
 * context to theme with (unknown workspace, unknown path). */
export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <div className="max-w-[380px] text-center">
        <Wordmark className="text-[20px]" />
        <h1 className="mt-5 font-heading text-[25px] leading-[1.2] font-semibold">
          Page not found
        </h1>
        <p className="mt-2.5 text-[14.5px] leading-[22px] text-g600 [text-wrap:pretty]">
          There&apos;s nothing at this address. Check the link — paths and subdomains
          are exact.
        </p>
        <div className="mt-[22px] flex items-center justify-center">
          <Link
            href="/"
            className="inline-flex h-10 items-center rounded-md border-[1.5px] border-edge px-[18px] text-[13.5px] font-semibold hover:border-accent hover:text-accent"
          >
            Go to the homepage
          </Link>
        </div>
      </div>
    </main>
  );
}
