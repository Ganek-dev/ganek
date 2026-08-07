import { describe, expect, it } from "vitest";

import {
  brandForeground,
  brandStyle,
  contrastRatio,
  isBrandRadius,
  parseHex,
  relativeLuminance,
} from "./brand";

describe("brand", () => {
  it("parses 3- and 6-digit hex", () => {
    expect(parseHex("#fff")).toEqual([255, 255, 255]);
    expect(parseHex("#18181b")).toEqual([24, 24, 27]);
    expect(parseHex("#E4572E")).toEqual([228, 87, 46]);
    expect(parseHex("not-a-color")).toBeNull();
    expect(parseHex("#12345")).toBeNull();
  });

  it("computes relative luminance at the extremes", () => {
    expect(relativeLuminance("#000000")).toBe(0);
    expect(relativeLuminance("#ffffff")).toBeCloseTo(1);
  });

  it("picks readable foregrounds (luminance > 0.45 → dark text)", () => {
    expect(brandForeground("#ffffff")).toBe("#18181b"); // light brand → dark text
    expect(brandForeground("#f5d90a")).toBe("#18181b"); // yellow → dark text
    expect(brandForeground("#18181b")).toBe("#ffffff"); // near-black → white
    expect(brandForeground("#E4572E")).toBe("#ffffff"); // demo brand orange → white
    expect(brandForeground("#6D28D9")).toBe("#ffffff"); // vetd purple → white
  });

  it("brandStyle sets both CSS variables and falls back on bad input", () => {
    expect(brandStyle("#E4572E")).toEqual({
      "--brand-primary": "#E4572E",
      "--brand-primary-foreground": "#ffffff",
    });
    const fallback = brandStyle(undefined);
    expect(fallback["--brand-primary" as keyof typeof fallback]).toBe("#18181b");
    expect(brandStyle("javascript:alert(1)")).toEqual(brandStyle(undefined));
  });

  it("contrastRatio is symmetric, WCAG-scaled, null on bad input", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#000000")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    // near-black brand on white text clears AA comfortably
    expect(contrastRatio("#18181b", brandForeground("#18181b"))!).toBeGreaterThan(4.5);
    expect(contrastRatio("nope", "#ffffff")).toBeNull();
  });

  it("brandStyle layers radius token overrides for sharp/round only", () => {
    const round = brandStyle("#E4572E", "round") as Record<string, string>;
    expect(round["--radius-lg"]).toBe("18px");
    const sharp = brandStyle("#E4572E", "sharp") as Record<string, string>;
    expect(sharp["--radius-lg"]).toBe("6px");
    const untouched = brandStyle("#E4572E", "default") as Record<string, string>;
    expect(untouched["--radius-lg"]).toBeUndefined();
    expect(brandStyle("#E4572E", "pill")).toEqual(brandStyle("#E4572E"));
    expect(isBrandRadius("round")).toBe(true);
    expect(isBrandRadius("pill")).toBe(false);
  });
});
