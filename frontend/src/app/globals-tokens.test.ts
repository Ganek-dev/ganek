import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// A gN utility class whose token is missing from the @theme block renders
// NOTHING — the class silently emits no CSS. That shipped once as invisible
// light-mode timeline bars on the integrity screen (bg-g300/70 with no
// --color-g300 mapping), so this scan locks every used gray to a mapping.

const SRC = join(process.cwd(), "src");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.tsx?$/.test(name) ? [full] : [];
  });
}

describe("gray token coverage", () => {
  it("every gN utility class used in src has a --color-gN mapping", () => {
    const theme = readFileSync(join(SRC, "app", "globals.css"), "utf8");
    const used = new Set<string>();
    for (const file of walk(SRC)) {
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(
        /(?:text|bg|border|divide|ring|fill|stroke)-g(\d{3})\b/g,
      )) {
        used.add(match[1]);
      }
    }
    expect(used.size).toBeGreaterThan(0); // the scan itself must find something
    for (const n of [...used].sort()) {
      expect(theme, `--color-g${n} is not mapped in globals.css @theme`).toContain(
        `--color-g${n}:`,
      );
    }
  });
});
