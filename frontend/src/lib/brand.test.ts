import { describe, expect, it } from "vitest";

import { brandForeground, brandStyle, parseHex, relativeLuminance } from "./brand";

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
});
