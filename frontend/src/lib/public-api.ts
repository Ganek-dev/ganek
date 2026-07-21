/** Server-side fetchers for the public careers API. Server components only. */

import "server-only";

import type { EmploymentType, RemotePolicy } from "@/lib/api";

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
  tags: string[];
  published_at: string | null;
}

export interface PublicJobDetail extends PublicJobSummary {
  description_md: string;
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

async function get<T>(path: string): Promise<T | null> {
  const resp = await fetch(`${BACKEND_URL}${path}`, { cache: "no-store" });
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`Backend responded ${resp.status} for ${path}`);
  return (await resp.json()) as T;
}

export async function fetchInstanceMode(): Promise<"single" | "multi"> {
  const health = await get<{ mode: "single" | "multi" }>("/api/health");
  return health?.mode ?? "single";
}

export const publicApi = {
  companyPage: (slug: string) => get<PublicCompanyPage>(`/api/v1/public/companies/${slug}`),
  companyJob: (slug: string, jobSlug: string) =>
    get<PublicJobDetail>(`/api/v1/public/companies/${slug}/jobs/${jobSlug}`),
  singleCompanyPage: () => get<PublicCompanyPage>("/api/v1/public/company"),
  singleCompanyJob: (jobSlug: string) =>
    get<PublicJobDetail>(`/api/v1/public/company/jobs/${jobSlug}`),
};
