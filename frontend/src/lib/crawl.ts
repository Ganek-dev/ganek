/** Paths no crawler may index on any host: admin plus every tokened
 * candidate surface - those URLs are capability links and must never end up
 * in a search index. Shared by the instance robots.txt and a tenant careers
 * host's robots.txt. */
export const ROBOTS_DISALLOW = [
  "/admin",
  "/application/",
  "/interview/",
  "/invite/",
  "/login",
  "/review",
  "/quiz/",
  "/reset",
  "/setup",
  "/verify",
];

function xmlEscape(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export interface SitemapJob {
  slug: string;
  published_at: string | null;
}

/** A tenant careers sitemap rooted at its canonical careers URL
 * (`careers_url`: the verified custom domain or tenant subdomain, else the
 * slug URL): the landing page, the privacy notice and every published job,
 * on the same URLs the pages declare as rel=canonical. */
export function tenantSitemapXml(careersUrl: string, jobs: SitemapJob[]): string {
  const base = careersUrl.replace(/\/+$/, "");
  const entry = (loc: string, changefreq: string, lastmod?: string | null) =>
    [
      "<url>",
      `<loc>${xmlEscape(loc)}</loc>`,
      lastmod ? `<lastmod>${xmlEscape(lastmod)}</lastmod>` : "",
      `<changefreq>${changefreq}</changefreq>`,
      "</url>",
    ].join("");
  const urls = [
    entry(`${base}/`, "daily"),
    entry(`${base}/privacy`, "monthly"),
    ...jobs.map((job) =>
      entry(`${base}/jobs/${encodeURIComponent(job.slug)}`, "weekly", job.published_at),
    ),
  ];
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls,
    "</urlset>",
    "",
  ].join("\n");
}

/** robots.txt for a tenant careers host: the instance's disallow list and
 * the host's own sitemap; a demo instance disallows everything. */
export function tenantRobotsTxt(careersUrl: string, demo: boolean): string {
  if (demo) return "User-Agent: *\nDisallow: /\n";
  const base = careersUrl.replace(/\/+$/, "");
  return [
    "User-Agent: *",
    ...ROBOTS_DISALLOW.map((path) => `Disallow: ${path}`),
    "",
    `Sitemap: ${base}/sitemap.xml`,
    "",
  ].join("\n");
}
