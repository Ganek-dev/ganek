import { tenantSitemapXml } from "@/lib/crawl";
import { publicApi } from "@/lib/public-api";

// The job list changes at runtime; never freeze this at build time.
export const dynamic = "force-dynamic";

/** A tenant's careers sitemap (the folder is not named sitemap.xml: Next
 * would take that for a metadata route). The middleware serves it as /sitemap.xml on
 * the tenant's verified custom domain or subdomain; URLs are built on the
 * company's canonical careers URL. Unknown or suspended tenant: 404. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ slug: string }> },
): Promise<Response> {
  const { slug } = await params;
  let page = null;
  try {
    page = await publicApi.companyPage(slug);
  } catch {
    page = null;
  }
  const careersUrl = page?.company.careers_url;
  if (!page || !careersUrl) {
    return new Response("Not found", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
  return new Response(tenantSitemapXml(careersUrl, page.jobs), {
    headers: { "Content-Type": "application/xml; charset=utf-8" },
  });
}
