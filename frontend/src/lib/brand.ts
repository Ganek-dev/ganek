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

/** Inline style carrying the brand CSS variables for a candidate surface. */
export function brandStyle(primary?: unknown): CSSProperties {
  const color =
    typeof primary === "string" && parseHex(primary) !== null ? primary : DEFAULT_BRAND;
  return {
    "--brand-primary": color,
    "--brand-primary-foreground": brandForeground(color),
  } as CSSProperties;
}
