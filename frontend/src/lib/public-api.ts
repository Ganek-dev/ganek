/** Server-side fetchers for the public careers API. Server components only. */

import "server-only";

import type { EmploymentType, RemotePolicy, SalaryPeriod } from "@/lib/api";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface PublicJobSummary {
  slug: string;
  title: string;
  location: string;
  remote_policy: RemotePolicy;
  employment_type: EmploymentType;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: SalaryPeriod;
  tags: string[];
  published_at: string | null;
}

export interface PublicJobDetail extends PublicJobSummary {
  description_md: string;
  /** Advisory deadline → JSON-LD validThrough; the posting stays applyable. */
  closes_at: string | null;
}

export interface PublicCompany {
  slug: string;
  name: string;
  description: string;
  logo_url: string | null;
  website: string | null;
  socials: Record<string, unknown>;
  theme: Record<string, unknown>;
}

export interface PublicCompanyPage {
  company: PublicCompany;
  jobs: PublicJobSummary[];
}

/** Per-company variables for the privacy notice page (M5.6 G1).
 * Fallbacks (legal name, retention default) are applied server-side. */
export interface PublicPrivacyNotice {
  /** a self-hosted proof-of-work check runs before public forms submit */
  captcha_enabled?: boolean;
  company_name: string;
  legal_name: string;
  privacy_contact_email: string | null;
  retention_months: number;
  privacy_policy_url: string | null;
  brand_primary: string | null;
  logo_url: string | null;
}

async function get<T>(path: string, headers?: Record<string, string>): Promise<T | null> {
  const resp = await fetch(`${BACKEND_URL}${path}`, {
    cache: "no-store",
    ...(headers ? { headers } : {}),
  });
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`Backend responded ${resp.status} for ${path}`);
  return (await resp.json()) as T;
}

export interface InstanceInfo {
  mode: "single" | "multi";
  /** public demo instance: banner, no CV field, no indexing (GANEK_DEMO_MODE) */
  demo: boolean;
}

/** /auth/providers from the server side; a backend hiccup never takes a
 * public page down, it just renders as a normal instance. */
export async function fetchInstanceInfo(): Promise<InstanceInfo> {
  try {
    const info = await get<{ mode?: "single" | "multi"; demo?: boolean }>(
      "/api/v1/auth/providers",
    );
    return { mode: info?.mode ?? "single", demo: info?.demo === true };
  } catch {
    return { mode: "single", demo: false };
  }
}

/** Metadata fragment for a demo instance: fake vacancies must never be indexed. */
export function demoRobots(demo: boolean): { robots?: { index: false; follow: false } } {
  return demo ? { robots: { index: false, follow: false } } : {};
}

export async function fetchInstanceMode(): Promise<"single" | "multi"> {
  const health = await get<{ mode: "single" | "multi" }>("/api/health");
  return health?.mode ?? "single";
}

/** `?preview=<token>` lets a recruiter's signed link render an unpublished
 * job (spec job posts v2 5.3). Absent or empty: the normal published lookup. */
function previewQuery(preview?: string): string {
  return preview ? `?preview=${encodeURIComponent(preview)}` : "";
}

export interface JobView {
  job: PublicJobDetail | null;
  /** true only when the job rendered BECAUSE of the token: a published job
   * opened with a token is the live page, token ignored */
  previewing: boolean;
}

/** Resolve a job page's data. With a token the backend may answer for an
 * unpublished job; a second plain lookup tells whether the token mattered,
 * so a live job never shows the preview bar (previews are rare, two
 * requests are fine). */
export async function resolveJobView(
  fetchJob: (preview?: string) => Promise<PublicJobDetail | null>,
  preview?: string,
): Promise<JobView> {
  const job = await fetchJob(preview);
  if (job === null || !preview) return { job, previewing: false };
  const live = await fetchJob();
  return { job, previewing: live === null };
}

/** `headers` carries the view headers (`lib/views.ts`) on the one page-render
 * fetch that counts; metadata and preview lookups never pass them. */
export const publicApi = {
  companyPage: (slug: string) => get<PublicCompanyPage>(`/api/v1/public/companies/${slug}`),
  companyJob: (slug: string, jobSlug: string, preview?: string, headers?: Record<string, string>) =>
    get<PublicJobDetail>(
      `/api/v1/public/companies/${slug}/jobs/${jobSlug}${previewQuery(preview)}`,
      headers,
    ),
  singleCompanyPage: () => get<PublicCompanyPage>("/api/v1/public/company"),
  singleCompanyJob: (jobSlug: string, preview?: string, headers?: Record<string, string>) =>
    get<PublicJobDetail>(
      `/api/v1/public/company/jobs/${jobSlug}${previewQuery(preview)}`,
      headers,
    ),
  companyPrivacy: (slug: string) =>
    get<PublicPrivacyNotice>(`/api/v1/public/companies/${slug}/privacy`),
  singlePrivacy: () => get<PublicPrivacyNotice>("/api/v1/public/company/privacy"),
};
