"use client";

import { useEffect, useState } from "react";

import { Check, Copy } from "lucide-react";

import { SettingsTabs } from "@/components/SettingsTabs";
import { companyApi, type CompanyAdmin } from "@/lib/api";
import {
  DEFAULT_BRAND,
  brandForeground,
  brandStyle,
  contrastRatio,
  parseHex,
  type BrandRadius,
} from "@/lib/brand";

/** Branding settings, handoff screen 10: brand color with AA check, corner
 * radius picker, careers domain, and a live candidate-surface preview.
 * Logo upload needs its own storage flow — the card ships with Replace
 * disabled until that lands. */

const RADIUS_OPTIONS: { value: BrandRadius; label: string }[] = [
  { value: "sharp", label: "sharp" },
  { value: "default", label: "default" },
  { value: "round", label: "round" },
];

const labelCls = "text-[13.5px] font-semibold";
const hintCls = "text-[12.5px] leading-[18px] text-g500";

export default function BrandingPage() {
  const [company, setCompany] = useState<CompanyAdmin | null>(null);
  const [color, setColor] = useState<string>(DEFAULT_BRAND);
  const [radius, setRadius] = useState<BrandRadius>("default");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [logoBusy, setLogoBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    companyApi
      .get()
      .then((data) => {
        setCompany(data);
        setColor(data.theme.primary_color ?? DEFAULT_BRAND);
        setRadius(data.theme.radius ?? "default");
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load company"),
      );
  }, []);

  const validColor = parseHex(color) !== null;
  const previewColor = validColor ? color : DEFAULT_BRAND;
  const contrast = contrastRatio(previewColor, brandForeground(previewColor));
  const aaOk = contrast !== null && contrast >= 4.5;

  async function save() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const updated = await companyApi.updateBranding({
        primary_color: color === DEFAULT_BRAND ? null : color,
        radius: radius === "default" ? null : radius,
      });
      setCompany(updated);
      setNotice("Branding saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save branding");
    } finally {
      setBusy(false);
    }
  }

  async function uploadLogo(file: File) {
    setError(null);
    setNotice(null);
    if (file.size > 2 * 1024 * 1024) {
      setError("Logo must be 2 MB or smaller");
      return;
    }
    setLogoBusy(true);
    try {
      setCompany(await companyApi.uploadLogo(file));
      setNotice("Logo updated");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload logo");
    } finally {
      setLogoBusy(false);
    }
  }

  async function removeLogo() {
    setError(null);
    setNotice(null);
    setLogoBusy(true);
    try {
      setCompany(await companyApi.removeLogo());
      setNotice("Logo removed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove logo");
    } finally {
      setLogoBusy(false);
    }
  }

  async function copyDomain() {
    if (company === null) return;
    try {
      await navigator.clipboard.writeText(`${company.slug}.vetd.dev`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Couldn't copy to clipboard");
    }
  }

  if (company === null) {
    return (
      <section className="space-y-4">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : (
          <div aria-busy="true" className="space-y-2">
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-lg bg-muted-fill" />
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
      <SettingsTabs />

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          {notice}
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <div className="card flex items-center gap-4 p-4">
            {company.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- served by our own API, host unknown at build time
              <img
                src={company.logo_url}
                alt="Company logo"
                className="h-12 w-12 shrink-0 rounded-lg border border-edge bg-surface object-contain"
              />
            ) : (
              <div
                aria-hidden
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg text-lg font-bold"
                style={{ background: previewColor, color: brandForeground(previewColor) }}
              >
                {company.name.charAt(0).toUpperCase()}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className={labelCls}>Logo</p>
              <p className={hintCls}>PNG, JPG, or SVG · max 2 MB · shown on all candidate pages</p>
            </div>
            {company.logo_url ? (
              <button
                type="button"
                disabled={logoBusy}
                onClick={removeLogo}
                className="inline-flex h-8 items-center rounded-md px-2 text-[13px] font-medium text-red-600 hover:bg-muted-fill disabled:opacity-50 dark:text-red-400"
              >
                Remove
              </button>
            ) : null}
            <label className="inline-flex h-8 cursor-pointer items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill">
              {logoBusy ? "…" : company.logo_url ? "Replace" : "Upload"}
              <input
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,.png,.jpg,.jpeg,.svg"
                disabled={logoBusy}
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (file) uploadLogo(file);
                }}
                className="sr-only"
              />
            </label>
          </div>

          <div className="card space-y-3 p-4">
            <div>
              <p className={labelCls}>Brand color</p>
              <p className={hintCls}>
                Drives headers, buttons, timers, and selection on candidate pages.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="color"
                aria-label="Brand color picker"
                value={validColor ? color : DEFAULT_BRAND}
                onChange={(event) => setColor(event.target.value)}
                className="h-9 w-12 cursor-pointer rounded-md border border-edge bg-transparent p-1"
              />
              <input
                type="text"
                aria-label="Brand color hex"
                value={color}
                onChange={(event) => setColor(event.target.value.trim())}
                spellCheck={false}
                className="h-9 w-28 rounded-md border border-edge bg-transparent px-3 font-mono text-[13px] outline-none focus:border-g400"
              />
              {validColor ? (
                aaOk ? (
                  <span className="inline-flex h-6 items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 text-[11.5px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
                    <Check aria-hidden className="h-3 w-3" />
                    AA contrast ok
                  </span>
                ) : (
                  <span className="inline-flex h-6 items-center rounded-full border border-amber-200 bg-amber-50 px-2 text-[11.5px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                    contrast below AA
                  </span>
                )
              ) : (
                <span className="inline-flex h-6 items-center rounded-full border border-edge bg-muted-fill px-2 text-[11.5px] font-medium text-g500">
                  enter #rrggbb
                </span>
              )}
            </div>
          </div>

          <div className="card space-y-3 p-4">
            <p className={labelCls}>Corner radius</p>
            <div
              role="radiogroup"
              aria-label="Corner radius"
              className="inline-flex rounded-md border border-edge p-0.5"
            >
              {RADIUS_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={radius === option.value}
                  onClick={() => setRadius(option.value)}
                  className={`inline-flex h-7 items-center rounded-[6px] px-3 text-[12.5px] font-medium ${
                    radius === option.value
                      ? "bg-inverse text-inverse-foreground"
                      : "text-g500 hover:text-g700"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="card flex items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <p className={labelCls}>Careers domain</p>
              <p className="mt-1 font-mono text-[13px] text-g700">{company.slug}.vetd.dev</p>
            </div>
            <button
              type="button"
              onClick={copyDomain}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill"
            >
              {copied ? (
                <Check aria-hidden className="h-3.5 w-3.5 text-emerald-600" />
              ) : (
                <Copy aria-hidden className="h-3.5 w-3.5" />
              )}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>

          <button
            type="button"
            onClick={save}
            disabled={busy || !validColor}
            className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-[13.5px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
          >
            {busy ? "…" : "Save branding"}
          </button>
        </div>

        <aside aria-label="Live preview" className="space-y-2">
          <p className="font-mono text-[11px] text-g400">Live preview — what candidates see</p>
          <div
            style={brandStyle(previewColor, radius)}
            className="card space-y-4 p-5"
            data-testid="branding-preview"
          >
            <div className="flex items-center gap-2.5">
              {company.logo_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- served by our own API, host unknown at build time
                <img
                  src={company.logo_url}
                  alt=""
                  className="h-7 w-7 rounded-md bg-white object-contain"
                />
              ) : (
                <span
                  aria-hidden
                  className="flex h-7 w-7 items-center justify-center rounded-md text-[13px] font-bold"
                  style={{
                    background: "var(--brand-primary)",
                    color: "var(--brand-primary-foreground)",
                  }}
                >
                  {company.name.charAt(0).toUpperCase()}
                </span>
              )}
              <span className="text-sm font-semibold">{company.name}</span>
              <span className="ml-auto text-[12px] text-g500">Careers</span>
            </div>
            <p className="font-heading text-[17px] font-semibold tracking-[-0.01em]">
              Work at {company.name}
            </p>
            <div className="space-y-2">
              {[
                { title: "Senior Frontend Engineer", meta: "Remote · 2w" },
                { title: "Backend Engineer (Python)", meta: "Berlin · 3w" },
              ].map((job) => (
                <div
                  key={job.title}
                  className="flex items-center justify-between rounded-lg border border-edge px-3.5 py-2.5"
                >
                  <span className="text-[13.5px] font-medium">{job.title}</span>
                  <span className="font-mono text-[11px] text-g400">{job.meta}</span>
                </div>
              ))}
            </div>
            <div
              className="flex h-10 items-center justify-center rounded-lg text-[13.5px] font-semibold"
              style={{
                background: "var(--brand-primary)",
                color: "var(--brand-primary-foreground)",
              }}
            >
              Apply for this position
            </div>
            <div className="flex items-center gap-2">
              <span
                className="inline-flex h-6 items-center rounded-full px-2.5 font-mono text-[11.5px] font-semibold"
                style={{
                  background: "color-mix(in oklab, var(--brand-primary) 12%, transparent)",
                  color: "var(--brand-primary)",
                }}
              >
                0:14
              </span>
              <span className="font-mono text-[11px] text-g400">
                quiz timer inherits the brand
              </span>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
