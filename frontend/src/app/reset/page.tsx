import Link from "next/link";

import { AuthShell } from "@/components/AuthShell";

export const metadata = {
  title: "Reset password · vetd",
  robots: { index: false, follow: false },
};

/** Reset password, handoff screen 13c. Backend reset flow lands with D5's
 * email suite — until then we show an informational page that points at
 * the workspace admin. Keeps the design surface without a broken form. */
export default function ResetPasswordPage() {
  return (
    <AuthShell
      title="Reset your password"
      subtitle={
        <>
          Password reset by email lands with the upcoming email suite. Until then, ask your
          workspace admin to set a new password from the Team page.
        </>
      }
      footer={
        <Link href="/login" className="font-medium text-accent hover:underline">
          ← Back to log in
        </Link>
      }
    >
      <div className="rounded-md border border-edge bg-muted-fill/40 px-4 py-3 text-[12.5px] leading-[19px] text-g600">
        <p>
          <span className="font-medium text-strong">Self-hosting?</span> An admin can reset a
          teammate&apos;s password directly against the database until the email flow ships.
        </p>
      </div>
    </AuthShell>
  );
}
