import { tenantRobotsTxt } from "@/lib/crawl";
import { fetchInstanceInfo, publicApi } from "@/lib/public-api";

export const dynamic = "force-dynamic";

/** robots.txt for a tenant's careers host. The middleware serves it as
 * /robots.txt on the verified custom domain or subdomain, pointing crawlers
 * at that host's own sitemap. Unknown or suspended tenant: 404. */
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
  const { demo } = await fetchInstanceInfo();
  return new Response(tenantRobotsTxt(careersUrl, demo), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
