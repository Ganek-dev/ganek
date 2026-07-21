/** Minimal typed wrapper around the Vetd API (proxied same-origin via Next rewrites). */

export interface UserOut {
  id: string;
  company_id: string;
  email: string;
  role: "admin" | "member";
}

export type RemotePolicy = "onsite" | "hybrid" | "remote";
export type EmploymentType = "full_time" | "part_time" | "contract" | "internship";
export type JobStatus = "draft" | "published" | "closed";

export interface JobOut {
  id: string;
  slug: string;
  title: string;
  description_md: string;
  location: string;
  remote_policy: RemotePolicy;
  employment_type: EmploymentType;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  tags: string[];
  status: JobStatus;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobInput {
  title: string;
  description_md: string;
  location: string;
  remote_policy: RemotePolicy;
  employment_type: EmploymentType;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  tags: string[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = (await resp.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  register: (payload: { company_name: string; email: string; password: string }) =>
    request<UserOut>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  login: (payload: { email: string; password: string }) =>
    request<UserOut>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  me: () => request<UserOut>("/api/v1/auth/me"),

  jobs: {
    list: () => request<JobOut[]>("/api/v1/jobs"),
    get: (id: string) => request<JobOut>(`/api/v1/jobs/${id}`),
    create: (payload: JobInput) =>
      request<JobOut>("/api/v1/jobs", { method: "POST", body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<JobInput>) =>
      request<JobOut>(`/api/v1/jobs/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    publish: (id: string) => request<JobOut>(`/api/v1/jobs/${id}/publish`, { method: "POST" }),
    close: (id: string) => request<JobOut>(`/api/v1/jobs/${id}/close`, { method: "POST" }),
    delete: (id: string) => request<void>(`/api/v1/jobs/${id}`, { method: "DELETE" }),
  },
};

export interface CvUploadTicket {
  upload_url: string;
  object_key: string;
  content_type: string;
  max_size_mb: number;
}

export interface ApplicationPayload {
  name: string;
  email: string;
  message: string | null;
  github: string | null;
  linkedin: string | null;
  portfolio: string | null;
  cv_object_key: string;
  cv_filename: string;
}

export const publicApply = {
  uploadTicket: (basePath: string) =>
    request<CvUploadTicket>(`${basePath}/apply/upload-url`, { method: "POST" }),
  submit: (basePath: string, payload: ApplicationPayload) =>
    request<{ status: string }>(`${basePath}/apply`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadCv: async (ticket: CvUploadTicket, file: File): Promise<void> => {
    const resp = await fetch(ticket.upload_url, {
      method: "PUT",
      body: file,
      headers: { "Content-Type": ticket.content_type },
    });
    if (!resp.ok) throw new ApiError(resp.status, "CV upload failed — please try again");
  },
};
