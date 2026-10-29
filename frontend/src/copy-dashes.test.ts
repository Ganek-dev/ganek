import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/** Owner rule: never an em or en dash in any copy, plain "-" only, and
 * no arrow glyph either (words or a lucide icon instead). The sweep
 * (board card "Copy sweep") cleared frontend/src; this keeps it clear
 * without a reviewer having to notice. Tests may spell a glyph as an
 * escape when they assert its absence. */

const ROOT = join(__dirname);
const DASH = /[\u2013\u2014\u2192]/;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    if (!/\.(ts|tsx)$/.test(name) || /\.test\.(ts|tsx)$/.test(name)) return [];
    return [path];
  });
}

describe("copy has no em or en dashes or arrow glyphs", () => {
  it("frontend/src (tests excluded)", () => {
    const offenders = sources(ROOT).flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .flatMap((line, i) => (DASH.test(line) ? [`${relative(ROOT, file)}:${i + 1}: ${line.trim()}`] : [])),
    );
    expect(offenders).toEqual([]);
  });
});
