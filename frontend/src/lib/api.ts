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
  /** Seconds per question; null = each question's own limit. */
  time_limit_seconds: number | null;
  /** Allowed difficulties; null/empty = all. */
  difficulties: Difficulty[] | null;
  /** Question ids excluded from this job's quiz. */
  exclude_ids: string[];
  /** Attached questionnaire — its ordered refs replace tag-auto selection. */
  questionnaire_id: string | null;
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
    quizPreview: (id: string) => request<QuizPreview>(`/api/v1/jobs/${id}/quiz-preview`),
  },
};

export interface QuizPreviewQuestion {
  id: string;
  source: "seed" | "company";
  tags: string[];
  difficulty: Difficulty;
  prompt_md: string;
  options: Record<string, string>;
  correct_key: string;
  excluded: boolean;
  blocked: boolean;
}

export interface QuizPreview {
  enabled: boolean;
  tags: string[];
  question_count: number;
  time_limit_seconds: number | null;
  difficulties: Difficulty[];
  pool: QuizPreviewQuestion[];
  eligible_count: number;
  eligible_by_tag: Record<string, number>;
  sample_question_ids: string[];
}

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
    request<{ status: string; quiz_token: string | null; status_token: string | null }>(
      `${basePath}/apply`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
  /** PUT the CV to the presigned URL. Uses XHR so callers can observe upload
   * progress (screen 03's mono % + progress bar); fetch has no upload events. */
  uploadCv: (
    ticket: CvUploadTicket,
    file: File,
    onProgress?: (fraction: number) => void,
  ): Promise<void> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", ticket.upload_url);
      xhr.setRequestHeader("Content-Type", ticket.content_type);
      if (onProgress) {
        xhr.upload.addEventListener("progress", (event) => {
          if (event.lengthComputable && event.total > 0) {
            onProgress(event.loaded / event.total);
          }
        });
      }
      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else reject(new ApiError(xhr.status, "CV upload failed — please try again"));
      });
      xhr.addEventListener("error", () =>
        reject(new ApiError(0, "CV upload failed — please try again")),
      );
      xhr.send(file);
    }),
};

export type ApplicationStage =
  | "new"
  | "screening"
  | "interview"
  | "offer"
  | "hired"
  | "rejected"
  | "withdrawn"; // candidate-initiated via the status page; recruiters never set it

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
  setStage: (id: string, stage: ApplicationStage, notifyCandidate = false) =>
    request<ApplicationOut>(`/api/v1/applications/${id}/stage`, {
      method: "PATCH",
      body: JSON.stringify({ stage, notify_candidate: notifyCandidate }),
    }),
  cvUrl: (id: string) =>
    request<{ download_url: string }>(`/api/v1/applications/${id}/cv-url`),
  remind: (id: string) =>
    request<{ sent: boolean }>(`/api/v1/applications/${id}/remind`, { method: "POST" }),
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
  candidate_name: string;
  company_name: string;
  job_title: string;
  brand_primary: string | null;
  seconds_per_question: number | null;
  expires_at: string;
  practice_available: boolean;
  status_token: string;
}

export interface PracticeQuestion {
  id: string;
  prompt_md: string;
  options: QuizOption[];
  time_limit_seconds: number;
}

export interface QuizNext {
  done: boolean;
  question: QuizQuestion | null;
}

export interface StatusQuiz {
  status: "pending" | "in_progress" | "completed" | "expired";
  answered: number;
  total: number;
  completed_at: string | null;
}

export interface ApplicationStatus {
  company_name: string;
  brand_primary: string | null;
  job_title: string;
  candidate_name: string;
  cv_filename: string;
  applied_at: string;
  stage: string;
  quiz: StatusQuiz | null;
  decision_expected_by: string;
}

export const publicApplications = {
  status: (token: string) =>
    request<ApplicationStatus>(`/api/v1/public/applications/${token}`),
  withdraw: (token: string) =>
    request<{ withdrawn: boolean }>(`/api/v1/public/applications/${token}/withdraw`, {
      method: "POST",
    }),
};

export const publicQuiz = {
  state: (token: string) => request<QuizState>(`/api/v1/public/quiz/${token}`),
  next: (token: string) => request<QuizNext>(`/api/v1/public/quiz/${token}/next`, { method: "POST" }),
  practice: (token: string) =>
    request<{ question: PracticeQuestion | null }>(`/api/v1/public/quiz/${token}/practice`, {
      method: "POST",
    }),
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

/** Difficulty is a 1-5 scale (5-dot UI); legacy "easy/medium/hard" bands were migrated. */
export type Difficulty = number;

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

export interface BankQuestion {
  id: string;
  domain: string;
  prompt_md: string;
  options: Record<string, string>;
  correct_key: string;
  explanation_md: string;
  tags: string[];
  difficulty: Difficulty;
  time_limit_seconds: number;
  blocked: boolean;
}

export interface BankPage {
  items: BankQuestion[];
  total: number;
  tags: string[];
}

export interface ResolvedQuestion {
  id: string;
  prompt_md: string;
  tags: string[];
  difficulty: Difficulty;
  time_limit_seconds: number;
  source: "seed" | "company";
  status: "active" | "retired";
  blocked: boolean;
}

export const questions = {
  list: () => request<QuestionOut[]>("/api/v1/questions"),
  create: (payload: QuestionInput) =>
    request<QuestionOut>("/api/v1/questions", { method: "POST", body: JSON.stringify(payload) }),
  retire: (id: string) => request<QuestionOut>(`/api/v1/questions/${id}`, { method: "DELETE" }),
  bank: (filters?: {
    tag?: string;
    difficulty?: Difficulty;
    q?: string;
    limit?: number;
    offset?: number;
  }) => {
    const params = new URLSearchParams();
    if (filters?.tag) params.set("tag", filters.tag);
    if (filters?.difficulty !== undefined) params.set("difficulty", String(filters.difficulty));
    if (filters?.q) params.set("q", filters.q);
    if (filters?.limit !== undefined) params.set("limit", String(filters.limit));
    if (filters?.offset !== undefined) params.set("offset", String(filters.offset));
    const qs = params.toString();
    return request<BankPage>(`/api/v1/questions/bank${qs ? `?${qs}` : ""}`);
  },
  block: (id: string) =>
    request<void>(`/api/v1/questions/bank/${id}/block`, { method: "PUT" }),
  unblock: (id: string) =>
    request<void>(`/api/v1/questions/bank/${id}/block`, { method: "DELETE" }),
  resolve: (ids: string[]) => {
    if (ids.length === 0) return Promise.resolve([] as ResolvedQuestion[]);
    const qs = new URLSearchParams({ ids: ids.join(",") }).toString();
    return request<ResolvedQuestion[]>(`/api/v1/questions/resolve?${qs}`);
  },
  usage: (ids: string[]) => {
    if (ids.length === 0) return Promise.resolve({} as Record<string, number>);
    const qs = new URLSearchParams({ ids: ids.join(",") }).toString();
    return request<Record<string, number>>(`/api/v1/questions/usage?${qs}`);
  },
};

export interface QuestionnaireOut {
  id: string;
  name: string;
  description: string;
  shuffle: boolean;
  question_refs: string[];
  created_at: string;
  updated_at: string;
}

export interface QuestionnaireInput {
  name: string;
  description?: string;
  shuffle?: boolean;
  question_refs?: string[];
}

export const questionnaires = {
  list: () => request<QuestionnaireOut[]>("/api/v1/questionnaires"),
  get: (id: string) => request<QuestionnaireOut>(`/api/v1/questionnaires/${id}`),
  create: (payload: QuestionnaireInput) =>
    request<QuestionnaireOut>("/api/v1/questionnaires", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, patch: Partial<QuestionnaireInput>) =>
    request<QuestionnaireOut>(`/api/v1/questionnaires/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  delete: (id: string) =>
    request<void>(`/api/v1/questionnaires/${id}`, { method: "DELETE" }),
};

export interface StatsOverview {
  jobs: { draft: number; published: number; closed: number };
  applications: { total: number; new: number; last_7_days: number };
  quiz: {
    attempts_total: number;
    attempts_completed: number;
    completion_rate: number | null;
    avg_score: number | null;
    median_score: number | null;
    avg_duration_seconds: number | null;
    /** ten 10%-wide buckets over 0-1 scores; index 9 includes 1.0 */
    score_distribution: number[];
  };
  per_job: {
    job_id: string;
    title: string;
    status: JobStatus;
    applications: number;
    new: number;
  }[];
  weekly: { week_start: string; count: number }[];
  recent: {
    id: string;
    candidate_name: string;
    job_id: string;
    job_title: string;
    stage: ApplicationStage;
    quiz_score: number | null;
    created_at: string;
  }[];
}

export const stats = {
  overview: () => request<StatsOverview>("/api/v1/stats/overview"),
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
