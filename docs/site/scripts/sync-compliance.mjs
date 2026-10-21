// Copies docs/compliance/*.md (the single source of truth, linked from the
// README, CONTRIBUTING and .env.example) into the Starlight content tree with
// the frontmatter Starlight needs. Sibling links become site routes; the edit
// link points at the original file. Output is gitignored.
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "compliance");
const target = join(here, "..", "src", "content", "docs", "compliance");

const ORDER = [
  "README.md",
  "self-hosting-gdpr-guide.md",
  "dpia-template.md",
  "records-of-processing-template.md",
  "breach-runbook.md",
  "telemetry-legitimate-interests.md",
  "ai-act-statement.md",
];

function route(file) {
  return file === "README.md" ? "/compliance/" : `/compliance/${basename(file, ".md")}/`;
}

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });

const files = readdirSync(source).filter((f) => f.endsWith(".md"));
for (const file of files) {
  const raw = readFileSync(join(source, file), "utf8");
  const lines = raw.split("\n");
  const h1 = lines.findIndex((l) => l.startsWith("# "));
  if (h1 === -1) throw new Error(`${file}: no H1`);
  const title = lines[h1].slice(2).trim();
  const body = [...lines.slice(0, h1), ...lines.slice(h1 + 1)]
    .join("\n")
    .replace(/\]\((?:\.\/)?([A-Za-z0-9-]+\.md)(#[^)]*)?\)/g, (_m, name, hash) => `](${route(name)}${hash ?? ""})`);
  const order = ORDER.indexOf(file);
  const front = [
    "---",
    `title: ${JSON.stringify(title)}`,
    `editUrl: https://github.com/Ganek-dev/ganek/edit/main/docs/compliance/${file}`,
    `sidebar: { order: ${order === -1 ? 99 : order}${file === "README.md" ? ', label: "Overview"' : ""} }`,
    "---",
    "",
  ].join("\n");
  const out = file === "README.md" ? "index.md" : file;
  writeFileSync(join(target, out), front + body.trimStart());
}
console.log(`synced ${files.length} compliance pages`);
