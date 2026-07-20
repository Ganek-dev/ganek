/** Minimal typed wrapper around the Vetd API (proxied same-origin via Next rewrites). */

export interface UserOut {
  id: string;
  company_id: string;
  email: string;
  role: "admin" | "member";
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
};
