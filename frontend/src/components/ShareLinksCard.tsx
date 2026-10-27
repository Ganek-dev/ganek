"use client";

import { useState } from "react";

import { ExternalLink } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import {
  CUSTOM_NAME_HINT,
  EMBED_DOCS_URL,
  SHARE_PRESETS,
  builtInSourceHint,
  shareUrl,
  sourceLabelFor,
} from "@/lib/share-links";
import { normalizeLinkName } from "@/lib/source";

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

const CUSTOM_INPUT_ID = "share-custom-name";
const CUSTOM_STATUS_ID = "share-custom-status";
const CUSTOM_PREVIEW_ID = "share-custom-preview";

/** Shown instead of the skeleton when the company summary failed: the
 * public URL cannot be built, so no link can (mirrors the URL card's
 * "Public link loads with the company"). */
export const SHARE_LINKS_UNAVAILABLE = "Share links load with the company.";

export function ShareLinksCard({
  jobUrl,
  live,
  urlFailed = false,
}: {
  jobUrl: string | null;
  live: boolean;
  /** the company summary failed, so `jobUrl` will stay null */
  urlFailed?: boolean;
}) {
  const [custom, setCustom] = useState("");
  const customName = normalizeLinkName(custom);
  const typed = custom.trim() !== "";
  const label = customName === null ? null : sourceLabelFor(customName);
  // a label without the link: prefix is a built-in bucket (or a utm alias of one)
  const builtIn = label !== null && !label.startsWith("link:");
  const refused = label === "direct";
  const invalid = typed && (customName === null || refused);
  const status = !typed
    ? ""
    : customName === null
      ? CUSTOM_NAME_HINT
      : builtIn
        ? builtInSourceHint(label)
        : `appears as ${label} in Sources`;

  return (
    <div className="card px-5 py-[18px]">
      <span className="font-heading text-[15px] font-semibold">Share this job</span>
      {!live ? (
        <p className="mt-3 text-sm text-g500">Publish to get share links.</p>
      ) : jobUrl === null && urlFailed ? (
        <p className="mt-3 text-sm text-g500">{SHARE_LINKS_UNAVAILABLE}</p>
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
            <label htmlFor={CUSTOM_INPUT_ID} className="block text-[12.5px] font-medium text-g700">
              Custom link name
            </label>
            <input
              id={CUSTOM_INPUT_ID}
              value={custom}
              onChange={(event) => setCustom(event.target.value)}
              placeholder="q4-push"
              aria-invalid={invalid}
              aria-describedby={
                typed && !invalid ? `${CUSTOM_STATUS_ID} ${CUSTOM_PREVIEW_ID}` : CUSTOM_STATUS_ID
              }
              className="mt-1.5 h-8 w-full rounded-md border border-edge bg-surface px-2.5 font-mono text-[12px] text-foreground aria-[invalid=true]:border-red-500"
            />
            {typed && !invalid && customName !== null ? (
              <ul id={CUSTOM_PREVIEW_ID} className="mt-2">
                <LinkRow
                  label="Custom"
                  url={shareUrl(jobUrl, customName)}
                  copyLabel="Copy custom link"
                />
              </ul>
            ) : null}
            {/* always mounted so the announcement works on the first invalid keystroke */}
            <p
              id={CUSTOM_STATUS_ID}
              aria-live="polite"
              className="mt-1.5 min-h-[14px] font-mono text-[11px] text-g500"
            >
              {status}
            </p>
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
