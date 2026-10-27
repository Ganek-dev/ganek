"use client";

import { useState } from "react";

import { ExternalLink } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import {
  CUSTOM_NAME_HINT,
  EMBED_DOCS_URL,
  SHARE_PRESETS,
  customShareName,
  shareUrl,
  sourceLabelFor,
} from "@/lib/share-links";

/** "Share this job" rail card (spec job posts v2 5.2 item 5): one ready
 * URL per channel plus a custom name, each with Copy. Pure frontend: the
 * `?src=` value lands in the source bucket that views and applications
 * already report under. */

/** Protocol-less base and the `?src=` part apart: the rail is 320px wide, so
 * the base may truncate but the part that differs per row never does. */
function splitDisplay(url: string): { base: string; suffix: string } {
  const shown = url.replace(/^https?:\/\//, "");
  const at = shown.lastIndexOf("src=") - 1; // the ? or & before src=
  return { base: shown.slice(0, at), suffix: shown.slice(at) };
}

function LinkRow({ label, url, copyLabel }: { label: string; url: string; copyLabel: string }) {
  const { base, suffix } = splitDisplay(url);
  return (
    <li className="flex items-center gap-2">
      <span className="w-[76px] shrink-0 text-[12.5px] font-medium text-g700">{label}</span>
      <span
        title={url}
        className="flex min-w-0 flex-1 items-baseline font-mono text-[11.5px] text-g500"
      >
        <span className="min-w-0 truncate">{base}</span>
        <span className="shrink-0 text-g700">{suffix}</span>
      </span>
      <CopyButton text={url} label={copyLabel} />
    </li>
  );
}

/** The preset rows alone: the rail card and the chart's "No views yet.
 * Share it:" state render the same links. */
export function ShareLinkRows({ jobUrl, className }: { jobUrl: string; className: string }) {
  return (
    <ul className={className}>
      {SHARE_PRESETS.map((preset) => (
        <LinkRow
          key={preset.name}
          label={preset.label}
          url={shareUrl(jobUrl, preset.name)}
          copyLabel={`Copy ${preset.label} link`}
        />
      ))}
    </ul>
  );
}

export function ShareLinksCard({ jobUrl, live }: { jobUrl: string | null; live: boolean }) {
  const [custom, setCustom] = useState("");
  const customName = customShareName(custom);

  return (
    <div className="card px-5 py-[18px]">
      <span className="font-heading text-[15px] font-semibold">Share this job</span>
      {!live ? (
        <p className="mt-3 text-sm text-g500">Publish to get share links.</p>
      ) : jobUrl === null ? (
        <div aria-busy="true" aria-label="Loading share links" className="mt-3 space-y-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-5 animate-pulse rounded-sm bg-muted-fill" />
          ))}
        </div>
      ) : (
        <>
          <ShareLinkRows jobUrl={jobUrl} className="mt-3 space-y-2" />
          <div className="mt-3 border-t border-divider pt-3">
            <label className="block text-[12.5px] font-medium text-g700">
              Custom name
              <input
                aria-label="Custom link name"
                value={custom}
                onChange={(event) => setCustom(event.target.value)}
                placeholder="q4-push"
                className="mt-1.5 h-8 w-full rounded-md border border-edge bg-surface px-2.5 font-mono text-[12px] text-foreground"
              />
            </label>
            {custom.trim() === "" ? null : customName === null ? (
              <p className="mt-1.5 font-mono text-[11px] text-g500">{CUSTOM_NAME_HINT}</p>
            ) : (
              <>
                <ul className="mt-2">
                  <LinkRow
                    label="Custom"
                    url={shareUrl(jobUrl, customName)}
                    copyLabel="Copy custom link"
                  />
                </ul>
                <p className="mt-1.5 font-mono text-[11px] text-g500">
                  appears as {sourceLabelFor(customName)} in Sources
                </p>
              </>
            )}
          </div>
          <p className="mt-3 text-[11.5px] text-g500">
            Name links after channels, never after a person.
          </p>
          <a
            href={EMBED_DOCS_URL}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex items-center gap-1 text-[12.5px] font-medium text-accent hover:underline"
          >
            How to embed jobs on your site
            <ExternalLink aria-hidden className="h-3 w-3" />
          </a>
        </>
      )}
    </div>
  );
}
