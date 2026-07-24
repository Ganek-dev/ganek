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

export interface QuizConfig {
  enabled: boolean;
  tags: string[] | null;
  question_count: number;
  include_company_questions: boolean;
}

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
  quiz_config: QuizConfig;
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
  quiz_config: QuizConfig;
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
  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

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
    request<{ status: string; quiz_token: string | null }>(`${basePath}/apply`, {
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

export type ApplicationStage =
  | "new"
  | "screening"
  | "interview"
  | "offer"
  | "hired"
  | "rejected";

export interface CandidateOut {
  id: string;
  name: string;
  email: string;
  links: Record<string, string>;
}

export interface IntegrityFlag {
  code: string;
  summary: string;
  detail: string;
  question_ids: string[];
}

export interface QuizIntegrity {
  blur_count?: number;
  blur_total_ms?: number;
  paste_count?: number;
  resize_count?: number;
  avg_answer_ms?: number;
  flags?: IntegrityFlag[];
}

export interface QuizResult {
  status: "pending" | "in_progress" | "completed" | "expired";
  score: number | null;
  per_tag_scores: Record<string, { correct: number; total: number }>;
  completed_at: string | null;
  question_ids: string[];
  integrity: QuizIntegrity;
}

export interface ApplicationOut {
  id: string;
  job_id: string;
  candidate: CandidateOut;
  cv_filename: string;
  cv_size: number;
  message: string | null;
  stage: ApplicationStage;
  source: string | null;
  quiz_attempt: QuizResult | null;
  created_at: string;
}

export const applications = {
  list: (filters?: { job_id?: string; stage?: ApplicationStage }) => {
    const params = new URLSearchParams();
    if (filters?.job_id) params.set("job_id", filters.job_id);
    if (filters?.stage) params.set("stage", filters.stage);
    const qs = params.toString();
    return request<ApplicationOut[]>(`/api/v1/applications${qs ? `?${qs}` : ""}`);
  },
  setStage: (id: string, stage: ApplicationStage) =>
    request<ApplicationOut>(`/api/v1/applications/${id}/stage`, {
      method: "PATCH",
      body: JSON.stringify({ stage }),
    }),
  cvUrl: (id: string) =>
    request<{ download_url: string }>(`/api/v1/applications/${id}/cv-url`),
  quizAnswers: (id: string) =>
    request<QuizAnswerReview[]>(`/api/v1/applications/${id}/quiz-answers`),
};

export interface ReviewIntegrityEvent {
  type: string;
  duration_ms: number | null;
}

export interface QuizAnswerReview {
  question_id: string;
  prompt_md: string;
  options: Record<string, string>;
  correct_key: string;
  explanation_md: string;
  tags: string[];
  answer_key: string | null;
  is_correct: boolean;
  response_ms: number | null;
  integrity_events: ReviewIntegrityEvent[];
}

export interface QuizOption {
  key: string;
  text_md: string;
}

export interface QuizQuestion {
  id: string;
  prompt_md: string;
  options: QuizOption[];
  time_limit_seconds: number;
  deadline_at: string;
  index: number;
  total: number;
}

export interface QuizState {
  status: "pending" | "in_progress" | "completed" | "expired";
  answered: number;
  total: number;
}

export interface QuizNext {
  done: boolean;
  question: QuizQuestion | null;
}

export const publicQuiz = {
  state: (token: string) => request<QuizState>(`/api/v1/public/quiz/${token}`),
  next: (token: string) => request<QuizNext>(`/api/v1/public/quiz/${token}/next`, { method: "POST" }),
  answer: (token: string, questionId: string, answerKey: string) =>
    request<{ recorded: boolean }>(`/api/v1/public/quiz/${token}/answer`, {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, answer_key: answerKey }),
    }),
  events: (
    token: string,
    events: { type: "blur" | "paste" | "resize"; duration_ms?: number; question_id?: string }[],
  ) =>
    request<{ recorded: boolean }>(`/api/v1/public/quiz/${token}/events`, {
      method: "POST",
      body: JSON.stringify({ events }),
    }),
};

export type Difficulty = "easy" | "medium" | "hard";

export interface QuestionOut {
  id: string;
  prompt_md: string;
  options: Record<string, string>;
  correct_key: string;
  explanation_md: string;
  tags: string[];
  difficulty: Difficulty;
  time_limit_seconds: number;
  status: "active" | "retired";
  created_at: string;
}

export interface QuestionInput {
  prompt_md: string;
  options: Record<string, string>;
  correct_key: string;
  explanation_md: string;
  tags: string[];
  difficulty: Difficulty;
  time_limit_seconds: number;
}

export const questions = {
  list: () => request<QuestionOut[]>("/api/v1/questions"),
  create: (payload: QuestionInput) =>
    request<QuestionOut>("/api/v1/questions", { method: "POST", body: JSON.stringify(payload) }),
  retire: (id: string) => request<QuestionOut>(`/api/v1/questions/${id}`, { method: "DELETE" }),
};

export type UserRole = "admin" | "member";

export interface TeamUser {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export const team = {
  list: () => request<TeamUser[]>("/api/v1/users"),
  create: (email: string, password: string, role: UserRole) =>
    request<TeamUser>("/api/v1/users", {
      method: "POST",
      body: JSON.stringify({ email, password, role }),
    }),
  update: (id: string, patch: { role?: UserRole; is_active?: boolean }) =>
    request<TeamUser>(`/api/v1/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
};
