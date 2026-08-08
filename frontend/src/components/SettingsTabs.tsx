"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** Settings section tabs from handoff screen 10: Branding | Team | Account. */
const TABS = [
  { href: "/admin/branding", label: "Branding" },
  { href: "/admin/hiring", label: "Hiring" },
  { href: "/admin/team", label: "Team" },
  { href: "/admin/account", label: "Account" },
  { href: "/admin/developers", label: "Developers" },
];

export function SettingsTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="Settings sections" className="flex gap-1 border-b border-divider">
      {TABS.map((tab) => {
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
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
