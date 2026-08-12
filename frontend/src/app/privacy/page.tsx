import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PrivacyNotice } from "@/components/privacy-notice";
import { publicApi } from "@/lib/public-api";

export const metadata: Metadata = {
  title: "Privacy notice",
  robots: { index: false },
};

/** Single-mode twin of /c/[slug]/privacy — the instance's one company.
 * The backend 404s this route on multi-tenant instances. */
export default async function PrivacyPage() {
  const notice = await publicApi.singlePrivacy();
  if (!notice) notFound();
  return <PrivacyNotice notice={notice} backHref="/" />;
}
