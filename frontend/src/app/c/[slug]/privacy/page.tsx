import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PrivacyNotice } from "@/components/privacy-notice";
import { publicApi } from "@/lib/public-api";

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const notice = await publicApi.companyPrivacy(slug);
  if (!notice) return {};
  return {
    title: `Privacy notice — ${notice.company_name}`,
    robots: { index: false },
  };
}

export default async function CompanyPrivacyPage({ params }: Props) {
  const { slug } = await params;
  const notice = await publicApi.companyPrivacy(slug);
  if (!notice) notFound();
  return <PrivacyNotice notice={notice} backHref={`/c/${slug}`} />;
}
