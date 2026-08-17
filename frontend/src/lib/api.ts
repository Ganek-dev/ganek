/** Minimal typed wrapper around the Vetd API (proxied same-origin via Next rewrites). */

export interface UserOut {
  id: string;
  company_id: string;
  email: string;
  role: "admin" | "member";
  /** false = Google-only account (signed up via Google, no password set). */
  has_password: boolean;
  /** Only in the register response: multi-mode signup awaiting the inbox click. */
  pending_verification?: boolean;
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
    // FormData bodies must set their own multipart boundary header
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = (await resp.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        // FastAPI validation errors (422) arrive as a list — surface the
        // first message instead of the bare "Unprocessable Content"
        const first = body.detail[0] as { msg?: unknown } | undefined;
        if (typeof first?.msg === "string") detail = first.msg;
      }
    } catch {
      // non-JSON error body; keep statusText
    }
    // mid-session expiry anywhere in the admin app: back to login instead
    // of raw error strings sprinkled over whatever surface made the call
    if (
      resp.status === 401 &&
      typeof window !== "undefined" &&
      window.location.pathname.startsWith("/admin")
    ) {
      window.location.assign("/login");
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export interface DayWindow {
  start: string;
  end: string;
}

export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export interface Availability {
  /** "" when the recruiter hasn't set one — falls back to the company/UTC default. */
  timezone: string;
  days: Partial<Record<DayKey, DayWindow>>;
  is_default: boolean;
}

export interface AvailabilityIn {
  timezone: string;
  days: Partial<Record<DayKey, DayWindow>>;
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
  verifyEmail: (payload: { token: string }) =>
    request<UserOut>("/api/v1/auth/verify-email", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  resendVerification: (payload: { email: string }) =>
    request<void>("/api/v1/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  forgotPassword: (payload: { email: string }) =>
    request<void>("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  resetPassword: (payload: { token: string; new_password: string }) =>
    request<UserOut>("/api/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  me: () => request<UserOut>("/api/v1/auth/me"),
  providers: () =>
    request<{ google: boolean; mode: "single" | "multi" }>("/api/v1/auth/providers"),
  googleCalendar: {
    status: () =>
      request<{ connected: boolean; google_email: string | null; needs_reconnect: boolean }>(
        "/api/v1/users/me/google-calendar",
      ),
    disconnect: () =>
      request<void>("/api/v1/users/me/google-calendar", { method: "DELETE" }),
  },
  availability: {
    get: () => request<Availability>("/api/v1/users/me/availability"),
    set: (payload: AvailabilityIn) =>
      request<Availability>("/api/v1/users/me/availability", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
  },
  // the signed Google account token rides an httponly cookie, not the body
  googleSignup: (payload: { company_name: string }) =>
    request<UserOut>("/api/v1/auth/google/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  googleSignupPending: () =>
    request<{ email: string }>("/api/v1/auth/google/signup/pending"),
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

export interface JobsFeedItem {
  title: string;
  slug: string;
  location: string;
  remote_policy: RemotePolicy;
  employment_type: EmploymentType;
  tags: string[];
  apply_url: string;
  posted_at: string | null;
}

export interface JobsFeed {
  company: string;
  brand_primary: string | null;
  jobs: JobsFeedItem[];
}

/** Public jobs feed (screen 25): CORS-open JSON for third-party sites. */
export const publicJobsFeed = (slug: string) =>
  request<JobsFeed>(`/api/v1/public/companies/${slug}/jobs-feed`);

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
  /** Set on a RE-ISSUED attempt: where it came from and why (D6). */
  reissue?: {
    from_attempt_id: string;
    reason: "expired" | "integrity";
    mode: "auto" | "manual";
    by_user_id: string | null;
    at: string;
  };
  /** Human review of the flags (screen 24 "looks fine"). */
  review?: { decision: string; by_user_id: string; at: string };
  /** Candidate asked for a new link from the expired screen (27c). */
  reissue_requested?: { at: string; count: number };
}

export interface QuizResult {
  status: "pending" | "in_progress" | "completed" | "expired" | "invalidated";
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

export interface EmailDelivery {
  id: string;
  kind: string;
  status: "queued" | "sent" | "failed";
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface ApplicationPage {
  items: ApplicationOut[];
  total: number;
  /** Whole job-filtered set — the stage filter never narrows these. */
  stage_counts: Partial<Record<ApplicationStage, number>>;
}

export const applications = {
  list: (filters?: {
    job_id?: string;
    stage?: ApplicationStage;
    limit?: number;
    offset?: number;
  }) => {
    const params = new URLSearchParams();
    if (filters?.job_id) params.set("job_id", filters.job_id);
    if (filters?.stage) params.set("stage", filters.stage);
    if (filters?.limit !== undefined) params.set("limit", String(filters.limit));
    if (filters?.offset !== undefined) params.set("offset", String(filters.offset));
    const qs = params.toString();
    return request<ApplicationPage>(`/api/v1/applications${qs ? `?${qs}` : ""}`);
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
  /** Delivery trail (M5.7 H4): whether this application's emails went out. */
  emails: (id: string) => request<EmailDelivery[]>(`/api/v1/applications/${id}/emails`),
  get: (id: string) => request<ApplicationOut>(`/api/v1/applications/${id}`),
  reissueQuiz: (id: string) =>
    request<QuizResult>(`/api/v1/applications/${id}/quiz/reissue`, { method: "POST" }),
  dismissFlags: (id: string) =>
    request<QuizResult>(`/api/v1/applications/${id}/quiz/dismiss-flags`, { method: "POST" }),
  bulkReject: (applicationIds: string[], notifyCandidates: boolean) =>
    request<{ rejected: number; skipped: number }>("/api/v1/applications/bulk-reject", {
      method: "POST",
      body: JSON.stringify({
        application_ids: applicationIds,
        notify_candidates: notifyCandidates,
      }),
    }),
  /** Art. 17: erases the whole candidate (every application), admin-only. */
  eraseCandidate: (id: string) =>
    request<{ applications: number; google_event_failures: number }>(
      `/api/v1/applications/${id}/erase-candidate`,
      { method: "POST" },
    ),
  /** Art. 15/20: candidate-destined JSON bundle, admin-only. */
  dsarExport: (id: string) =>
    request<Record<string, unknown>>(`/api/v1/applications/${id}/dsar-export`),
  /** Art. 16: rectify the delivery address for every candidate link. */
  updateCandidateEmail: (id: string, email: string) =>
    request<ApplicationOut>(`/api/v1/applications/${id}/candidate-email`, {
      method: "PATCH",
      body: JSON.stringify({ email }),
    }),
};

export interface Note {
  id: string;
  body: string;
  /** null once the author's account is gone (e.g. removed teammate). */
  author_email: string | null;
  created_at: string;
}

export const notes = {
  list: (applicationId: string) => request<Note[]>(`/api/v1/applications/${applicationId}/notes`),
  add: (applicationId: string, body: string) =>
    request<Note>(`/api/v1/applications/${applicationId}/notes`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
  remove: (applicationId: string, noteId: string) =>
    request<void>(`/api/v1/applications/${applicationId}/notes/${noteId}`, { method: "DELETE" }),
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
  /** Effective retention window (server-resolved default) for the honest copy. */
  retention_months: number;
  /** Absolute link to the company's privacy notice. */
  privacy_url: string;
}

export interface InterviewPublic {
  company_name: string;
  brand_primary: string | null;
  logo_url: string | null;
  job_title: string;
  candidate_first_name: string;
  title: string;
  description: string;
  duration_minutes: number;
  timezone: string;
  status: "pending" | "booked" | "cancelled";
  interviewer_display: string;
  available_slots: string[];
  scheduled_start: string | null;
  meet_url: string | null;
}

export const publicInterviews = {
  get: (token: string) => request<InterviewPublic>(`/api/v1/public/interviews/${token}`),
  book: (token: string, start: string) =>
    request<InterviewPublic>(`/api/v1/public/interviews/${token}/book`, {
      method: "POST",
      body: JSON.stringify({ start }),
    }),
  reschedule: (token: string, start: string) =>
    request<InterviewPublic>(`/api/v1/public/interviews/${token}/reschedule`, {
      method: "POST",
      body: JSON.stringify({ start }),
    }),
  cancel: (token: string) =>
    request<InterviewPublic>(`/api/v1/public/interviews/${token}/cancel`, {
      method: "POST",
    }),
};

export interface InterviewAdmin {
  id: string;
  status: "pending" | "booked" | "cancelled";
  interviewer_user_id: string;
  interviewer_email: string;
  title: string;
  description: string;
  duration_minutes: number;
  timezone: string;
  scheduled_start: string | null;
  meet_url: string | null;
  created_at: string;
}

export const interviews = {
  preview: (
    applicationId: string,
    body: { interviewer_user_id: string; duration_minutes: number; timezone: string },
  ) =>
    request<{ schedule_summary: string; open_slot_count: number }>(
      `/api/v1/applications/${applicationId}/interview/slot-preview`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),
  create: (
    applicationId: string,
    body: {
      interviewer_user_id: string;
      duration_minutes: number;
      timezone: string;
      description: string;
    },
  ) =>
    request<InterviewAdmin>(`/api/v1/applications/${applicationId}/interview`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  get: (applicationId: string) =>
    request<InterviewAdmin | null>(`/api/v1/applications/${applicationId}/interview`),
  cancel: (applicationId: string) =>
    request<InterviewAdmin>(`/api/v1/applications/${applicationId}/interview/cancel`, {
      method: "POST",
    }),
};

export const publicApplications = {
  status: (token: string) =>
    request<ApplicationStatus>(`/api/v1/public/applications/${token}`),
  withdraw: (token: string) =>
    request<{ withdrawn: boolean }>(`/api/v1/public/applications/${token}/withdraw`, {
      method: "POST",
    }),
  /** Art. 15: asks the company for a copy — notify-only, never a download. */
  requestData: (token: string) =>
    request<{ status: string }>(`/api/v1/public/applications/${token}/request-data`, {
      method: "POST",
    }),
  /** Art. 17: asks the company to delete — notify-only, the controller decides. */
  requestDeletion: (token: string) =>
    request<{ status: string }>(`/api/v1/public/applications/${token}/request-deletion`, {
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
  /** Expired-link screen (27c): ask for a fresh link. reissued=true means a
   * new link was auto-emailed; false means the team was notified. */
  requestReissue: (token: string) =>
    request<{ reissued: boolean }>(`/api/v1/public/quiz/${token}/request-reissue`, {
      method: "POST",
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

export interface ActivityItem {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  actor_email: string | null;
  application_id: string | null;
  created_at: string;
}

export interface TaskItem {
  id: string;
  title: string;
  note: string;
  due_date: string | null;
  done_at: string | null;
  assignee_user_id: string | null;
  created_by: string | null;
  created_at: string;
}

export interface TodayPanelData {
  source: "google" | "vetd";
  events: { start: string | null; summary: string; hangout_link: string | null }[];
}

export const dashboard = {
  activity: (limit = 15) => request<ActivityItem[]>(`/api/v1/activity?limit=${limit}`),
  today: (tz: string) =>
    request<TodayPanelData>(`/api/v1/stats/today?tz=${encodeURIComponent(tz)}`),
  tasks: {
    list: () => request<TaskItem[]>("/api/v1/tasks"),
    create: (title: string, note = "") =>
      request<TaskItem>("/api/v1/tasks", {
        method: "POST",
        body: JSON.stringify({ title, note }),
      }),
    toggle: (id: string, done: boolean) =>
      request<TaskItem>(`/api/v1/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ done }),
      }),
    remove: (id: string) => request<void>(`/api/v1/tasks/${id}`, { method: "DELETE" }),
  },
};

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

export interface CompanyAdmin {
  slug: string;
  name: string;
  description: string;
  mode: "single" | "multi";
  smtp_configured: boolean;
  logo_url: string | null;
  website: string | null;
  socials: Record<string, unknown>;
  theme: { primary_color?: string; radius?: "sharp" | "default" | "round" };
  settings: {
    quiz_expired_reissue?: "manual" | "auto";
    legal_name?: string;
    privacy_contact_email?: string;
    retention_months?: number;
    privacy_policy_url?: string;
  };
}

/** Omit = untouched, null = reset to default (mirrors BrandingUpdate). */
export interface CompanySettingsUpdate {
  quiz_expired_reissue?: "manual" | "auto" | null;
  legal_name?: string | null;
  privacy_contact_email?: string | null;
  retention_months?: number | null;
  privacy_policy_url?: string | null;
}

export interface BrandingUpdate {
  /** Omit = untouched, null = reset to default. */
  primary_color?: string | null;
  radius?: "sharp" | "default" | "round" | null;
}

export const companyApi = {
  get: () => request<CompanyAdmin>("/api/v1/company"),
  updateBranding: (patch: BrandingUpdate) =>
    request<CompanyAdmin>("/api/v1/company/branding", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  updateSettings: (patch: CompanySettingsUpdate) =>
    request<CompanyAdmin>("/api/v1/company/settings", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  uploadLogo: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<CompanyAdmin>("/api/v1/company/logo", { method: "POST", body: form });
  },
  removeLogo: () => request<CompanyAdmin>("/api/v1/company/logo", { method: "DELETE" }),
  /** Sends a real email to the calling admin, surfacing transport errors. */
  testEmail: () =>
    request<{ sent: boolean }>("/api/v1/company/test-email", { method: "POST" }),
};

export interface TeamInvite {
  id: string;
  email: string;
  role: UserRole;
  created_at: string;
  expires_at: string;
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
  /** GDPR removal: tombstone in place (their interviews FK-block a hard delete). */
  anonymize: (id: string) =>
    request<void>(`/api/v1/users/${id}/anonymize`, { method: "POST" }),
  listInvites: () => request<TeamInvite[]>("/api/v1/users/invites"),
  invite: (email: string, role: UserRole) =>
    request<TeamInvite>("/api/v1/users/invites", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),
  resendInvite: (id: string) =>
    request<TeamInvite>(`/api/v1/users/invites/${id}/resend`, { method: "POST" }),
  revokeInvite: (id: string) =>
    request<void>(`/api/v1/users/invites/${id}`, { method: "DELETE" }),
};

export interface PublicInvite {
  email: string;
  company_name: string;
  role: UserRole;
}

/** Invite accept page (magic link from the team-invite email). */
export const publicInvites = {
  get: (token: string) => request<PublicInvite>(`/api/v1/public/invites/${token}`),
  accept: (token: string, password: string) =>
    request<UserOut>(`/api/v1/public/invites/${token}/accept`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
};
