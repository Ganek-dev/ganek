"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ArrowUpRight, Check } from "lucide-react";

import { api, companyApi, team, type CompanyAdmin } from "@/lib/api";
import { CopyButton } from "@/components/CopyButton";
import { careersDisplay, careersUrl } from "@/lib/careers";

/** First-run checklist, handoff screen 14: lives on the dashboard until all
 * five steps are done, then disappears for good. Completion is derived from
 * live data (no stored flags): branding theme, first job, first assessment,
 * team size/invites. Admin-only — the data it needs is admin-scoped, and
 * onboarding is the workspace owner's job. Any load error renders nothing:
 * onboarding must never break the dashboard. */

interface Step {
  title: string;
  hint: string;
  done: boolean;
  cta?: { label: string; href: string };
}

export function OnboardingChecklist() {
  const [company, setCompany] = useState<CompanyAdmin | null>(null);
  const [steps, setSteps] = useState<Step[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await api.me();
        if (me.role !== "admin") return;
        const [companyData, jobs, users, invites] = await Promise.all([
          companyApi.get(),
          api.jobs.list(),
          team.list(),
          team.listInvites(),
        ]);
        if (cancelled) return;
        const theme = companyData.theme;
        setCompany(companyData);
        setSteps([
          {
            title: "Create your workspace",
            hint: "done",
            done: true,
          },
          {
            title: "Brand your careers page",
            hint: "logo, color, corner radius — ~1 min",
            done:
              Boolean(theme.primary_color) ||
              Boolean(theme.radius) ||
              companyData.logo_url !== null,
            cta: { label: "Open branding", href: "/admin/branding" },
          },
          {
            title: "Post your first job",
            hint: "title, tags, description — draft is fine",
            done: jobs.length > 0,
            cta: { label: "Create job", href: "/admin/jobs/new" },
          },
          {
            title: "Attach a skills assessment",
            hint: "start from the curated question bank",
            done: jobs.some((job) => job.quiz_config.enabled),
            cta: { label: "Browse questions", href: "/admin/questions" },
          },
          {
            title: "Invite your team",
            hint: "admins and recruiters",
            done: users.length > 1 || invites.length > 0,
            cta: { label: "Invite", href: "/admin/team" },
          },
        ]);
      } catch {
        // leave steps null — the dashboard renders fine without the checklist
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (company === null || steps === null) return null;
  const doneCount = steps.filter((step) => step.done).length;
  if (doneCount === steps.length) return null;

  return (
    <div className="card p-4" data-testid="onboarding-checklist">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-heading text-[15.5px] font-semibold tracking-[-0.01em]">
            Let&apos;s get {company.name} hiring
          </p>
        </div>
        <span className="inline-flex h-6 items-center rounded-full border border-edge bg-muted-fill px-2.5 font-mono text-[11px] font-medium text-g600">
          {doneCount} of {steps.length} done
        </span>
      </div>

      <ul className="mt-3 space-y-1">
        {steps.map((step, index) => (
          <li key={step.title} className="flex items-center gap-3 rounded-md px-2 py-2">
            {step.done ? (
              <span
                aria-hidden
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
              >
                <Check aria-hidden className="h-3.5 w-3.5" />
              </span>
            ) : (
              <span
                aria-hidden
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-edge font-mono text-[11px] font-semibold text-g500"
              >
                {index + 1}
              </span>
            )}
            <div className="min-w-0 flex-1">
              <p
                className={`text-[13.5px] font-medium ${step.done ? "text-g500 line-through decoration-g500/40" : ""}`}
              >
                {step.title}
              </p>
              {!step.done ? <p className="text-[12px] text-g500">{step.hint}</p> : null}
            </div>
            {!step.done && step.cta ? (
              <Link
                href={step.cta.href}
                className="inline-flex h-7 items-center rounded-md border border-edge bg-surface px-2.5 text-[12.5px] font-medium text-g700 hover:bg-muted-fill"
              >
                {step.cta.label}
              </Link>
            ) : null}
          </li>
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-divider pt-3">
        <p className="font-mono text-[12px] text-g600">
          {careersDisplay(company.mode, company.slug)}
        </p>
        <CopyButton text={careersUrl(company.mode, company.slug)} label="Copy careers URL" />
        <a
          href="/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-7 items-center gap-1 rounded-md border border-edge bg-surface px-2 text-[12px] font-medium text-g700 hover:bg-muted-fill"
        >
          Open
          <ArrowUpRight aria-hidden className="h-3 w-3" />
        </a>
        <p className="ml-auto text-[12px] text-g400">
          You can skip any step — this checklist stays here until it&apos;s done.
        </p>
      </div>
    </div>
  );
}
