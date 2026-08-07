/** Per-company brand theming (design handoff §Architecture).
 *
 * Every brand-dependent value on candidate surfaces goes through CSS variables:
 * `--brand-primary` plus a computed `--brand-primary-foreground` (luminance
 * > 0.45 → dark text, else white). Never hard-code a brand color in
 * candidate components.
 */

import type { CSSProperties } from "react";

export const DEFAULT_BRAND = "#18181b";

const DARK_TEXT = "#18181b";
const LIGHT_TEXT = "#ffffff";

/** Parse #rgb / #rrggbb into [r, g, b] (0–255). Null when malformed. */
export function parseHex(color: string): [number, number, number] | null {
  const match = /^#(?:([0-9a-f]{3})|([0-9a-f]{6}))$/i.exec(color.trim());
  if (!match) return null;
  const hex = match[1] ? [...match[1]].map((c) => c + c).join("") : match[2];
  const value = Number.parseInt(hex, 16);
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

/** WCAG relative luminance, 0 (black) – 1 (white). */
export function relativeLuminance(color: string): number | null {
  const rgb = parseHex(color);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((channel) => {
    const c = channel / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Text color that stays readable on the given brand color. */
export function brandForeground(color: string): string {
  const luminance = relativeLuminance(color);
  if (luminance === null) return LIGHT_TEXT; // default brand is near-black
  return luminance > 0.45 ? DARK_TEXT : LIGHT_TEXT;
}

/** WCAG contrast ratio (1–21) between two hex colors. Null when malformed. */
export function contrastRatio(a: string, b: string): number | null {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  if (la === null || lb === null) return null;
  const [light, dark] = la >= lb ? [la, lb] : [lb, la];
  return (light + 0.05) / (dark + 0.05);
}

export type BrandRadius = "sharp" | "default" | "round";

/** Per-company corner radius: overrides the `--radius-*` tokens that
 * Tailwind's rounded-* utilities resolve at use site. "default" keeps the
 * globals.css scale (8/10/12/14). */
const RADIUS_SCALES: Record<BrandRadius, CSSProperties | null> = {
  sharp: {
    "--radius-sm": "2px",
    "--radius-md": "4px",
    "--radius-lg": "6px",
    "--radius-xl": "8px",
  } as CSSProperties,
  default: null,
  round: {
    "--radius-sm": "10px",
    "--radius-md": "14px",
    "--radius-lg": "18px",
    "--radius-xl": "22px",
  } as CSSProperties,
};

export function isBrandRadius(value: unknown): value is BrandRadius {
  return value === "sharp" || value === "default" || value === "round";
}

/** Inline style carrying the brand CSS variables for a candidate surface. */
export function brandStyle(primary?: unknown, radius?: unknown): CSSProperties {
  const color =
    typeof primary === "string" && parseHex(primary) !== null ? primary : DEFAULT_BRAND;
  const scale = isBrandRadius(radius) ? RADIUS_SCALES[radius] : null;
  return {
    "--brand-primary": color,
    "--brand-primary-foreground": brandForeground(color),
    ...scale,
  } as CSSProperties;
}
