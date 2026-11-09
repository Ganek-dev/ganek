"use client";

import { useEffect, useState } from "react";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { companyApi } from "@/lib/api";
import { useLocale } from "@/lib/i18n/locale";
import type { MessageKey } from "@/lib/i18n/messages";

/** Settings section tabs from handoff screen 10: Branding | Team | Account. */
const TABS: { href: string; label: MessageKey }[] = [
  { href: "/admin/branding", label: "settings.branding" },
  { href: "/admin/hiring", label: "settings.hiring" },
  { href: "/admin/privacy", label: "settings.privacy" },
  { href: "/admin/emails", label: "settings.emails" },
  { href: "/admin/team", label: "settings.team" },
  { href: "/admin/account", label: "settings.account" },
  { href: "/admin/developers", label: "settings.developers" },
];

/** Only a hosted instance with Stripe configured has a billing page. */
const BILLING_TAB: { href: string; label: MessageKey } = {
  href: "/admin/billing",
  label: "settings.billing",
};

export function SettingsTabs() {
  const pathname = usePathname();
  const { t } = useLocale();
  const [billing, setBilling] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(() => companyApi.plan())
      .then((plan) => {
        if (!cancelled) setBilling(plan.billing_enabled);
      })
      .catch(() => {
        // no plan answer: the tab stays hidden, the other tabs still work
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tabs = billing || pathname === BILLING_TAB.href ? [...TABS, BILLING_TAB] : TABS;
  return (
    <nav aria-label={t("settings.label")} className="flex gap-1 border-b border-divider">
      {tabs.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`-mb-px inline-flex h-9 items-center border-b-2 px-3 text-[13.5px] font-medium ${
              active
                ? "border-accent text-foreground"
                : "border-transparent text-g500 hover:text-g700"
            }`}
          >
            {t(tab.label)}
          </Link>
        );
      })}
    </nav>
  );
}
