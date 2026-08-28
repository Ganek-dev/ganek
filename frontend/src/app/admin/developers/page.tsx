"use client";

import { useEffect, useState } from "react";

import { ArrowUpRight } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import { SettingsTabs } from "@/components/SettingsTabs";
import { companyApi, publicJobsFeed, type JobsFeed } from "@/lib/api";

/** Developers page, handoff screen 25: the public jobs API (no auth, CORS,
 * cached 60s) and the embed widget snippet with a live preview. Careers
 * pages on ganek stay SSR with Google Jobs structured data — the widget is
 * for the company's own marketing site. */

type WidgetTheme = "auto" | "light" | "dark";

function sampleJson(slug: string, origin: string): string {
  return JSON.stringify(
    {
      company: "Your Company",
      brand_primary: "#7E14FF",
      jobs: [
        {
          title: "Senior Frontend Engineer",
          slug: "senior-frontend-engineer",
          location: "Remote — Europe",
          remote_policy: "remote",
          employment_type: "full_time",
          tags: ["react", "typescript", "senior"],
          apply_url: `${origin}/c/${slug}/jobs/senior-frontend-engineer`,
          posted_at: "2026-07-10T09:00:00Z",
        },
      ],
    },
    null,
    2,
  );
}

export default function DevelopersPage() {
  const [slug, setSlug] = useState<string | null>(null);
  const [feed, setFeed] = useState<JobsFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<WidgetTheme>("auto");
  const [showTags, setShowTags] = useState(true);
  // safe lazily: origin-dependent markup only renders after data loads,
  // so the SSR-prerendered skeleton never contains it
  const [origin] = useState(() =>
    typeof window === "undefined" ? "" : window.location.origin,
  );

  useEffect(() => {
    companyApi
      .get()
      .then((company) => {
        setSlug(company.slug);
        publicJobsFeed(company.slug)
          .then(setFeed)
          .catch(() => setFeed(null));
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load company"),
      );
  }, []);

  if (slug === null) {
    return (
      <section className="max-w-[880px] space-y-4">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : (
          <div aria-busy="true" className="space-y-2">
            {Array.from({ length: 2 }, (_, i) => (
              <div key={i} className="h-32 animate-pulse rounded-lg bg-muted-fill" />
            ))}
          </div>
        )}
      </section>
    );
  }

  const feedUrl = `${origin}/api/v1/public/companies/${slug}/jobs-feed`;
  const snippet =
    `<script src="${origin}/embed/jobs.js" data-workspace="${slug}"` +
    (theme !== "auto" ? ` data-theme="${theme}"` : "") +
    (showTags ? "" : ` data-tags="false"`) +
    `></script>`;

  return (
    <section className="max-w-[880px] space-y-4">
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
      <SettingsTabs />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <div className="card p-4">
            <div className="flex items-center justify-between">
              <p className="text-[13.5px] font-semibold">Jobs API</p>
              <a
                href={feedUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
              >
                Open feed
                <ArrowUpRight aria-hidden className="h-3 w-3" />
              </a>
            </div>
            <p className="mt-1 text-[12.5px] leading-[18px] text-g500">
              Public, no auth, CORS enabled, cached 60s. Your published jobs as JSON.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <span className="inline-flex h-6 items-center rounded-md bg-emerald-100 px-2 font-mono text-[11px] font-bold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                GET
              </span>
              <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-g700">
                {feedUrl}
              </code>
              <CopyButton text={feedUrl} label="Copy feed URL" />
            </div>
            <pre className="mt-3 overflow-x-auto rounded-md border border-edge bg-muted-fill/50 p-3 font-mono text-[11.5px] leading-[17px] text-g700">
              {sampleJson(slug, origin)}
            </pre>
          </div>

          <div className="card p-4">
            <p className="text-[13.5px] font-semibold">Embed widget</p>
            <p className="mt-1 text-[12.5px] leading-[18px] text-g500">
              Drop your open roles into your own site. Inherits your brand color; ~4 KB, no
              framework.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <code className="min-w-0 flex-1 overflow-x-auto rounded-md border border-edge bg-muted-fill/50 p-2.5 font-mono text-[11.5px] whitespace-nowrap text-g700">
                {snippet}
              </code>
              <CopyButton text={snippet} label="Copy embed snippet" />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4">
              <div
                role="radiogroup"
                aria-label="Widget theme"
                className="inline-flex rounded-md border border-edge p-0.5"
              >
                {(["auto", "light", "dark"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={theme === option}
                    onClick={() => setTheme(option)}
                    className={`inline-flex h-7 items-center rounded-[6px] px-3 text-[12.5px] font-medium ${
                      theme === option
                        ? "bg-inverse text-inverse-foreground"
                        : "text-g500 hover:text-g700"
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
              <label className="flex items-center gap-2 text-[13px] text-g700">
                <input
                  type="checkbox"
                  checked={showTags}
                  onChange={(event) => setShowTags(event.target.checked)}
                  className="h-4 w-4 accent-current"
                />
                Show tags
              </label>
            </div>
            <p className="mt-3 text-[12px] leading-[18px] text-g400">
              Careers pages on ganek stay SSR with Google Jobs structured data — the widget is
              for your marketing site.
            </p>
          </div>
        </div>

        <aside aria-label="Widget preview" className="space-y-2">
          <p className="font-mono text-[11px] text-g400">Widget preview — your live roles</p>
          <div className="card overflow-hidden" data-testid="widget-preview">
            <div className="flex items-baseline justify-between border-b border-divider px-4 py-3">
              <span className="text-[14px] font-semibold">Open positions</span>
              <span className="text-[12px] text-g500">
                {feed === null ? "…" : `${feed.jobs.length} role${feed.jobs.length === 1 ? "" : "s"}`}
              </span>
            </div>
            {feed === null ? (
              <div aria-busy="true" className="space-y-2 px-4 py-4">
                {Array.from({ length: 2 }, (_, i) => (
                  <div key={i} className="h-8 animate-pulse rounded-md bg-muted-fill" />
                ))}
              </div>
            ) : feed.jobs.length === 0 ? (
              <p className="px-4 py-4 text-[13px] text-g500">No open positions right now.</p>
            ) : (
              feed.jobs.map((job) => (
                <div key={job.slug} className="border-t border-divider px-4 py-3 first:border-t-0">
                  <p
                    className="text-[13.5px] font-semibold"
                    style={{ color: feed.brand_primary ?? undefined }}
                  >
                    {job.title}
                  </p>
                  <p className="mt-0.5 text-[12px] text-g500">{job.location}</p>
                  {showTags && job.tags.length > 0 ? (
                    <p className="mt-1.5 flex flex-wrap gap-1.5">
                      {job.tags.slice(0, 4).map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex h-5 items-center rounded-full bg-muted-fill px-2 text-[11px] text-g600"
                        >
                          {tag}
                        </span>
                      ))}
                    </p>
                  ) : null}
                </div>
              ))
            )}
            <p className="border-t border-divider px-4 py-2.5 font-mono text-[10.5px] text-g400">
              Careers powered by ganek
            </p>
          </div>
        </aside>
      </div>
    </section>
  );
}
