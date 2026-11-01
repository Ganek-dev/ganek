import type { PublicCompanyPage, PublicJobDetail } from "@/lib/public-api";
import type { RejectionReason } from "@/lib/rejection-reasons";

/** Minimal typed wrapper around the Ganek API (proxied same-origin via Next rewrites). */

export interface UserOut {
  id: string;
  company_id: string;
  email: string;
  role: "admin" | "member";
  /** false = Google-only account (signed up via Google, no password set). */
  has_password: boolean;
  /** Own display name (card D14); display_label is the server's fallback-applied label. */
  display_name?: string | null;
  display_label?: string;
  /** Only in the register response: multi-mode signup awaiting the inbox click. */
  pending_verification?: boolean;
  /** Second factor (card A6): on, and how many recovery codes are unused. */
  mfa_enabled?: boolean;
  recovery_codes_left?: number;
  /** Login response only: the password passed, a code is needed next. */
  mfa_required?: boolean;
  mfa_token?: string | null;
}

/** Per-tenant guards this instance enforces (GANEK_QUOTA_*); 0 = off. */
export interface InstanceLimits {
  active_jobs: number;
  applications_per_hour: number;
  emails_per_day: number;
}

/** GET /auth/providers: optional sign-in methods, deployment mode and the
 * limits the signup page lists under "what you get" (card B3). */
export interface Providers {
  google: boolean;
  mode: "single" | "multi";
  limits?: InstanceLimits;
  /** public demo instance (GANEK_DEMO_MODE): banner, locked account actions */
  demo?: boolean;
  /** the shared demo admin login, present only while demo is true */
  demo_login?: { email: string; password: string };
}

export type RemotePolicy = "onsite" | "hybrid" | "remote";
export type EmploymentType = "full_time" | "part_time" | "contract" | "internship";
export type SalaryPeriod = "hour" | "day" | "week" | "month" | "year";
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
  /** Attached questionnaire - its ordered refs replace tag-auto selection. */
  questionnaire_id: string | null;
}

/** Per-job screening questions (board card "Per-job screening questions").
 * `preferred` is recruiter-internal: the public job detail never carries it
 * and an answer never moves, mails or scores a candidate. */
export type ScreeningQuestionType = "yes_no" | "single_choice" | "short_text" | "acknowledgment";

export interface ScreeningQuestion {
  /** `sq_` + 8 hex; the server keeps a client-made id. */
  id: string;
  type: ScreeningQuestionType;
  prompt: string;
  /** single_choice only, 2 to 10 entries. */
  options: string[] | null;
  /** "yes" | "no" for yes_no, an option for single_choice, else null. */
  preferred: string | null;
  /** Always true for an acknowledgment. */
  required: boolean;
}

/** One stored answer with the question as it was asked (write-once snapshot). */
export interface ScreeningAnswer {
  question_id: string;
  type: ScreeningQuestionType;
  prompt: string;
  options: string[] | null;
  preferred: string | null;
  /** null = skipped optional question; true = acknowledgment accepted. */
  answer: string | boolean | null;
  /** null when there is no preferred answer or the question was skipped. */
  match: boolean | null;
}

export type ScreeningFilter = "match" | "mismatch" | "unanswered";

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
  salary_period: SalaryPeriod;
  closes_at: string | null;
  tags: string[];
  status: JobStatus;
  quiz_config: QuizConfig;
  screening_questions: ScreeningQuestion[];
  scorecard_template?: ScorecardCriterion[];
  published_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobInput {
  /** Omit on create to inherit the company default; a list replaces on update. */
  scorecard_template?: ScorecardCriterion[];
  title: string;
  description_md: string;
  location: string;
  remote_policy: RemotePolicy;
  employment_type: EmploymentType;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: SalaryPeriod;
  closes_at: string | null;
  tags: string[];
  quiz_config: QuizConfig;
  screening_questions: ScreeningQuestion[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    /** The response's raw `detail` when it was not a string (FastAPI's
     * validation list, the apply route's per-question errors). */
    public body?: unknown,
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
    let rawDetail: unknown;
    try {
      const body = (await resp.json()) as { detail?: unknown };
      rawDetail = body.detail;
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        // FastAPI validation errors (422) arrive as a list - surface the
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
    throw new ApiError(resp.status, detail, rawDetail);
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
  /** "" when the recruiter hasn't set one - falls back to the company/UTC default. */
  timezone: string;
  days: Partial<Record<DayKey, DayWindow>>;
  is_default: boolean;
  /** Default room or video link for this user's interviews; "" when none. */
  location: string;
}

export interface AvailabilityIn {
  timezone: string;
  days: Partial<Record<DayKey, DayWindow>>;
  location: string;
}

export const api = {
  register: (payload: {
    company_name: string;
    email: string;
    password: string;
    altcha?: string | null;
  }) =>
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
  /** Login step two: the authenticator code or a recovery code. */
  mfaVerify: (payload: { mfa_token: string; code: string }) =>
    request<UserOut>("/api/v1/auth/mfa", { method: "POST", body: JSON.stringify(payload) }),
  mfa: {
    enrol: () =>
      request<{ secret: string; otpauth_uri: string }>("/api/v1/auth/mfa/enrol", {
        method: "POST",
      }),
    confirm: (code: string) =>
      request<{ recovery_codes: string[] }>("/api/v1/auth/mfa/confirm", {
        method: "POST",
        body: JSON.stringify({ code }),
      }),
    disable: (payload: { password?: string; code?: string }) =>
      request<void>("/api/v1/auth/mfa/disable", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },
  signOutEverywhere: () =>
    request<void>("/api/v1/auth/sign-out-everywhere", { method: "POST" }),
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
  providers: () => request<Providers>("/api/v1/auth/providers"),
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
  updateProfile: (displayName: string | null) =>
    request<UserOut>("/api/v1/users/me", {
      method: "PATCH",
      body: JSON.stringify({ display_name: displayName }),
    }),
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
    stats: (id: string) => request<JobStats>(`/api/v1/jobs/${id}/stats`),
    /** 7-day signed link that renders the job as candidates will see it,
     * published or not; shareable with someone who has no login */
    previewLink: (id: string) =>
      request<PreviewLink>(`/api/v1/jobs/${id}/preview-link`, { method: "POST" }),
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
  /** Presigned POST policy fields; sent before the file as multipart/form-data. */
  upload_fields: Record<string, string>;
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
  /** both omitted on a demo instance, which attaches its sample CV instead */
  cv_object_key?: string;
  cv_filename?: string;
  /** solved proof-of-work payload; only when the instance renders the widget */
  altcha?: string | null;
  /** where the candidate came from (lib/source.ts grammar); null when unknown */
  source?: string | null;
  /** Answers to the job's screening questions; null = skipped optional. */
  screening_answers?: { question_id: string; answer: string | boolean | null }[];
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
  /** POST the CV to the presigned URL as multipart/form-data (policy fields
   * first, file last; the signed policy caps the size). Uses XHR so callers
   * can observe upload progress (screen 03's mono % + progress bar); fetch
   * has no upload events. */
  uploadCv: (
    ticket: CvUploadTicket,
    file: File,
    onProgress?: (fraction: number) => void,
  ): Promise<void> =>
    new Promise((resolve, reject) => {
      const form = new FormData();
      for (const [name, value] of Object.entries(ticket.upload_fields)) {
        form.append(name, value);
      }
      form.append("file", file, file.name);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", ticket.upload_url);
      if (onProgress) {
        xhr.upload.addEventListener("progress", (event) => {
          if (event.lengthComputable && event.total > 0) {
            onProgress(event.loaded / event.total);
          }
        });
      }
      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else if (xhr.status === 400 && /EntityTooLarge/.test(xhr.responseText)) {
          // the bucket enforced the policy cap (client pre-check was bypassed)
          reject(new ApiError(413, `Your CV exceeds the ${ticket.max_size_mb} MB limit.`));
        } else reject(new ApiError(xhr.status, "CV upload failed - please try again"));
      });
      xhr.addEventListener("error", () =>
        reject(new ApiError(0, "CV upload failed - please try again")),
      );
      xhr.send(form);
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
    reason: "expired" | "integrity" | "accommodation";
    mode: "auto" | "manual";
    by_user_id: string | null;
    at: string;
  };
  /** Extra-time accommodation a recruiter granted (1.5 or 2); carried over on re-issue. */
  accommodation?: { time_multiplier: number; by_user_id: string | null; at: string };
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
  /** Frozen extra-time multiplier for this attempt: 1 (none), 1.5 or 2. */
  time_multiplier: number;
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
  /** When the row entered its current stage (sort "Longest in stage"). */
  stage_changed_at: string;
  /** Internal rejection reason and note (card "Candidate emails", PR 2):
   * set while the row is rejected or withdrawn, never shown to candidates. */
  rejection_reason: RejectionReason | null;
  rejection_note: string | null;
  /** Screening answer snapshots with preferred + match: recruiter-facing only. */
  screening_answers: ScreeningAnswer[];
}

/** The optional internal reason sent with a rejection; a key left
 * undefined is not sent at all. */
export interface RejectionFields {
  rejectionReason?: RejectionReason | null;
  rejectionNote?: string | null;
}

/** What a stage move may carry besides the stage: the internal rejection
 * fields and the email template for the mail it sends (card "Candidate
 * emails", PR 3): a template id, "builtin" for the Ganek default, null
 * for the kind's default. Undefined keys are not sent at all. */
export interface StageFields extends RejectionFields {
  templateId?: string | null;
  /** One-off edit of this send (PR 4): literal text, both or neither,
   * never saved to the template. Single moves only; bulk ignores them. */
  subject?: string;
  body?: string;
}

function rejectionBody(fields: StageFields): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (fields.rejectionReason !== undefined) body.rejection_reason = fields.rejectionReason;
  if (fields.rejectionNote !== undefined) body.rejection_note = fields.rejectionNote;
  if (fields.templateId !== undefined) body.template_id = fields.templateId;
  if (fields.subject !== undefined) body.subject = fields.subject;
  if (fields.body !== undefined) body.body = fields.body;
  return body;
}

/** One row of the applicant timeline (card "Candidate timeline"): an
 * activity type or applied / quiz.invited / quiz.started / quiz.completed /
 * quiz.expired / email, with the facts the copy needs in `payload`. */
export interface TimelineEvent {
  id: string;
  kind: string;
  at: string;
  actor_label: string | null;
  actor_email: string | null;
  payload: Record<string, unknown>;
}

/** One read of a candidate (read-access audit trail), newest first. */
export interface AccessEntry {
  id: string;
  action: "view" | "cv_download" | "quiz_answers" | "dsar_export" | string;
  actor_email: string | null;
  actor_label: string | null;
  api_key_name: string | null;
  created_at: string;
}

/** Company-wide access log row: the entry plus who the candidate was. */
export interface AccessLogRow extends AccessEntry {
  application_id: string;
  candidate_name: string;
  job_title: string;
}

export interface AccessLogFilters {
  actor_user_id?: string;
  api_key_id?: string;
  application_id?: string;
  action?: string;
}

export const accessLogApi = {
  /** Admins only (403 for members); newest first. */
  list: (params: AccessLogFilters & { limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") query.set(key, String(value));
    }
    const suffix = query.toString();
    return request<{ items: AccessLogRow[]; total: number }>(
      `/api/v1/access-log${suffix ? `?${suffix}` : ""}`,
    );
  },
  exportUrl: (filters: AccessLogFilters = {}) => {
    const params = new URLSearchParams({ format: "csv" });
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value);
    }
    return `/api/v1/access-log/export?${params.toString()}`;
  },
};

export interface ApplicationPage {
  items: ApplicationOut[];
  total: number;
  /** The whole set the other filters match - the stage filter never narrows these. */
  stage_counts: Partial<Record<ApplicationStage, number>>;
  /** Source facet for the filter control: company-wide, NULL folded into "direct". */
  sources: string[];
}

export type ApplicationSortKey =
  | "applied_desc"
  | "applied_asc"
  | "score_desc"
  | "score_asc"
  | "name_asc"
  | "stage_age_desc"
  | "stage_age_asc";

/** Latest-attempt state; "expired" also covers a pending link past its expiry. */
export type ApplicationQuizState = "none" | "pending" | "in_progress" | "completed" | "expired";

/** Filters the applicants list and its export share (one query grammar on
 * both routes, so the file is always the rows on screen). */
export interface ApplicationFilters {
  job_id?: string;
  stage?: ApplicationStage;
  /** Candidate name or email, substring, case-insensitive. */
  q?: string;
  /** Percent of the latest attempt, 0..100. */
  score_min?: number;
  quiz?: ApplicationQuizState;
  /** "direct" also matches applications without a recorded source. */
  source?: string;
  flagged?: boolean;
  /** Applied within the last N days, 1..365. */
  since_days?: number;
  screening?: ScreeningFilter;
  sort?: ApplicationSortKey;
  /** Export only: a selection (the bulk bar), at most 100. */
  ids?: string[];
}

function applicationParams(filters: ApplicationFilters | undefined): URLSearchParams {
  const params = new URLSearchParams();
  if (!filters) return params;
  if (filters.job_id) params.set("job_id", filters.job_id);
  if (filters.stage) params.set("stage", filters.stage);
  if (filters.q) params.set("q", filters.q);
  if (filters.score_min !== undefined) params.set("score_min", String(filters.score_min));
  if (filters.quiz) params.set("quiz", filters.quiz);
  if (filters.source) params.set("source", filters.source);
  if (filters.flagged !== undefined) params.set("flagged", String(filters.flagged));
  if (filters.since_days !== undefined) params.set("since_days", String(filters.since_days));
  if (filters.screening) params.set("screening", filters.screening);
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.ids && filters.ids.length > 0) params.set("ids", filters.ids.join(","));
  return params;
}

export type EmailKind = "quiz_invite" | "quiz_reminder" | "stage_advance" | "rejection";
/** A preview can also be a one-off message (PR 4). */
export type PreviewKind = EmailKind | "message";

export interface EmailPreview {
  kind: PreviewKind;
  subject: string;
  text: string;
  html: string;
  /** The template part alone, before the fixed action block: what "Edit
   * this email" prefills. */
  body: string;
}

export interface MessageInput {
  subject: string;
  body: string;
}

export const applications = {
  /** GET /applications/export as a plain download URL (card D9): a link
   * with the session cookie is enough, so no fetch and no blob juggling. */
  exportUrl: (format: "csv" | "json", filters?: ApplicationFilters) => {
    const params = new URLSearchParams({ format });
    for (const [key, value] of applicationParams(filters)) params.set(key, value);
    return `/api/v1/applications/export?${params.toString()}`;
  },
  list: (filters?: ApplicationFilters & { limit?: number; offset?: number }) => {
    const params = applicationParams(filters);
    if (filters?.limit !== undefined) params.set("limit", String(filters.limit));
    if (filters?.offset !== undefined) params.set("offset", String(filters.offset));
    const qs = params.toString();
    return request<ApplicationPage>(`/api/v1/applications${qs ? `?${qs}` : ""}`);
  },
  setStage: (
    id: string,
    stage: ApplicationStage,
    notifyCandidate = false,
    fields: StageFields = {},
  ) =>
    request<ApplicationOut>(`/api/v1/applications/${id}/stage`, {
      method: "PATCH",
      body: JSON.stringify({
        stage,
        notify_candidate: notifyCandidate,
        ...rejectionBody(fields),
      }),
    }),
  /** The stage mail rendered for this candidate, exactly what the sender
   * delivers (card "Candidate emails"); nothing is queued. */
  emailPreview: (id: string, kind: EmailKind, templateId?: string) =>
    request<EmailPreview>(
      `/api/v1/applications/${id}/email-preview?kind=${kind}` +
        (templateId ? `&template_id=${encodeURIComponent(templateId)}` : ""),
    ),
  /** A one-off message to the candidate (PR 4); replies go to the sender.
   * `queued` is false on a demo instance, where nothing is mailed. */
  sendMessage: (id: string, payload: MessageInput) =>
    request<{ queued: boolean }>(`/api/v1/applications/${id}/message`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  /** The one-off message as the candidate would receive it; nothing is queued. */
  messagePreview: (id: string, payload: MessageInput) =>
    request<EmailPreview>(`/api/v1/applications/${id}/message/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cvUrl: (id: string) =>
    request<{ download_url: string }>(`/api/v1/applications/${id}/cv-url`),
  remind: (id: string) =>
    request<{ sent: boolean }>(`/api/v1/applications/${id}/remind`, { method: "POST" }),
  quizAnswers: (id: string) =>
    request<QuizAnswerReview[]>(`/api/v1/applications/${id}/quiz-answers`),
  /** What happened to this application, newest first (card "Candidate timeline"). */
  timeline: (id: string) => request<TimelineEvent[]>(`/api/v1/applications/${id}/timeline`),
  /** Who looked at this candidate; admins only (403 for members). */
  accessLog: (id: string) => request<AccessEntry[]>(`/api/v1/applications/${id}/access-log`),
  get: (id: string) => request<ApplicationOut>(`/api/v1/applications/${id}`),
  reissueQuiz: (id: string) =>
    request<QuizResult>(`/api/v1/applications/${id}/quiz/reissue`, { method: "POST" }),
  /** Extra-time accommodation: 1 removes it, 1.5 and 2 grant it. A pending
   * attempt keeps its link; anything started is re-issued with the multiplier. */
  grantExtraTime: (id: string, timeMultiplier: number) =>
    request<QuizResult>(`/api/v1/applications/${id}/quiz/extra-time`, {
      method: "POST",
      body: JSON.stringify({ time_multiplier: timeMultiplier }),
    }),
  dismissFlags: (id: string) =>
    request<QuizResult>(`/api/v1/applications/${id}/quiz/dismiss-flags`, { method: "POST" }),
  bulkReject: (applicationIds: string[], notifyCandidates: boolean, fields: StageFields = {}) =>
    request<{ rejected: number; skipped: number }>("/api/v1/applications/bulk-reject", {
      method: "POST",
      body: JSON.stringify({
        application_ids: applicationIds,
        notify_candidates: notifyCandidates,
        ...rejectionBody(fields),
      }),
    }),
  /** Bulk bar "Move to": rows already there, withdrawn, foreign or unknown
   * are skipped and counted; each moved row gets its own activity entry. */
  bulkStage: (
    applicationIds: string[],
    stage: ApplicationStage,
    notifyCandidates: boolean,
    fields: StageFields = {},
  ) =>
    request<{ updated: number; skipped: number }>("/api/v1/applications/bulk-stage", {
      method: "POST",
      body: JSON.stringify({
        application_ids: applicationIds,
        stage,
        notify_candidates: notifyCandidates,
        ...rejectionBody(fields),
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

/** A scorecard criterion; new ones are sent with id "" and the server assigns
 * one. Saved ids must round-trip unchanged (submitted snapshots match on them). */
export interface ScorecardCriterion {
  id: string;
  label: string;
  hint: string;
}
export type Recommendation = "strong_no" | "no" | "yes" | "strong_yes";
export type ScorecardState = "open" | "submitted" | "dismissed" | "declined";

export interface Scorecard {
  id: string;
  application_id: string;
  reviewer_user_id: string | null;
  reviewer_label: string;
  requested_by_label: string | null;
  interview_id: string | null;
  requested_at: string;
  due_from: string;
  submitted_at: string | null;
  dismissed_at: string | null;
  declined_at: string | null;
  state: ScorecardState;
  waiting_days: number;
  criteria: ScorecardCriterion[];
  ratings: Record<string, number>;
  recommendation: Recommendation | null;
  comment: string | null;
  edited: boolean;
  can_edit: boolean;
}

export interface MyScorecard {
  id: string;
  application_id: string;
  candidate_name: string;
  job_title: string;
  requested_by_label: string | null;
  requested_at: string;
  due_from: string;
  waiting_days: number;
  state: ScorecardState;
  submitted_at: string | null;
  href: string;
}

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  strong_no: "Strong no",
  no: "No",
  yes: "Yes",
  strong_yes: "Strong yes",
};

/** "Waiting on Jane Doe for 4 days" / "for 1 day" / ", requested today". */
export function waitingCopy(label: string, days: number): string {
  if (days <= 0) return `Waiting on ${label}, requested today`;
  return `Waiting on ${label} for ${days} ${days === 1 ? "day" : "days"}`;
}

export const scorecards = {
  mine: (state: "open" | "all" = "open") =>
    request<MyScorecard[]>(`/api/v1/scorecards/mine?state=${state}`),
  list: (applicationId: string) =>
    request<Scorecard[]>(`/api/v1/scorecards/applications/${applicationId}`),
  requestFrom: (applicationId: string, reviewerUserId: string) =>
    request<Scorecard>(`/api/v1/scorecards/applications/${applicationId}`, {
      method: "POST",
      body: JSON.stringify({ reviewer_user_id: reviewerUserId }),
    }),
  dismiss: (scorecardId: string) =>
    request<void>(`/api/v1/scorecards/${scorecardId}/dismiss`, { method: "POST" }),
  submit: (
    applicationId: string,
    body: { ratings: Record<string, number>; recommendation: Recommendation; comment: string | null },
  ) =>
    request<Scorecard>(`/api/v1/scorecards/applications/${applicationId}/mine`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  decline: (applicationId: string) =>
    request<void>(`/api/v1/scorecards/applications/${applicationId}/mine/decline`, {
      method: "POST",
    }),
};

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
  // server clock when this payload was built; the client measures its skew
  // against it so the ring never shows time the server has already spent
  server_now: string;
  index: number;
  total: number;
}

export interface QuizState {
  status: "pending" | "in_progress" | "completed" | "expired";
  answered: number;
  timed_out: number;
  total: number;
  candidate_name: string;
  company_name: string;
  job_title: string;
  brand_primary: string | null;
  seconds_per_question: number | null;
  expires_at: string;
  practice_available: boolean;
  status_token: string;
  privacy_url: string;
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
  timed_out: number;
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
  /** Room or video link; "" when the interviewer set none. */
  location: string;
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
  location: string;
  created_at: string;
}

export interface SlotPreview {
  schedule_summary: string;
  open_slot_count: number;
  /** The interviewer's default location, prefilled into the dialog. */
  default_location: string;
}

export const interviews = {
  preview: (
    applicationId: string,
    body: { interviewer_user_id: string; duration_minutes: number; timezone: string },
  ) =>
    request<SlotPreview>(
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
      location: string;
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
  /** Art. 15: asks the company for a copy - notify-only, never a download. */
  requestData: (token: string) =>
    request<{ status: string }>(`/api/v1/public/applications/${token}/request-data`, {
      method: "POST",
    }),
  /** Art. 17: asks the company to delete - notify-only, the controller decides. */
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
  requestReissue: (token: string, altcha?: string | null) =>
    request<{ reissued: boolean }>(`/api/v1/public/quiz/${token}/request-reissue`, {
      method: "POST",
      body: JSON.stringify({ altcha: altcha ?? null }),
    }),
};

/** Difficulty is a 1-5 scale (5-dot UI); legacy "easy/medium/hard" bands were migrated. */
export type Difficulty = number;

export interface QuestionStats {
  served: number;
  correct_rate: number;
  timeout_rate: number;
  avg_response_ms: number | null;
  /** Fixed rule (20+ answers, more than 10 points outside the rating's band). */
  hint: "easier" | "harder" | null;
}

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
  /** Difficulty calibration from this workspace's completed quizzes; ids
   * never served here are absent. A report only, nothing in scoring reads it. */
  stats: (ids: string[]) => {
    if (ids.length === 0) return Promise.resolve({} as Record<string, QuestionStats>);
    const qs = new URLSearchParams({ ids: ids.join(",") }).toString();
    return request<Record<string, QuestionStats>>(`/api/v1/questions/stats?${qs}`);
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

export interface PreviewLink {
  url: string;
  expires_at: string;
}

/** One job's overview numbers (GET /jobs/{id}/stats). Counts only. */
export interface JobStats {
  applications: { total: number; new: number; last_7_days: number };
  last_30_days: number;
  /** stage value -> count; stages with no applications are absent */
  by_stage: Partial<Record<ApplicationStage, number>>;
  /** source label -> count ("direct" for applications without one) */
  by_source: Record<string, number>;
  quiz: StatsOverview["quiz"];
  weekly: { week_start: string; count: number }[];
  /** null for drafts and for jobs closed before closed_at existed */
  days_open: number | null;
  /** counted job page loads (spec 5.5): bots, prefetches, previews and
   * signed-in recruiters excluded; never unique visitors */
  views: { total: number; last_30_days: number };
  /** source label -> views, all time; same labels as by_source plus "other" */
  views_by_source: Record<string, number>;
  /** last 30 UTC days, oldest first, gaps filled */
  daily: { day: string; views: number; applications: number }[];
}

export interface StatsOverview {
  jobs: { draft: number; published: number; closed: number };
  applications: { total: number; new: number; last_7_days: number };
  quiz: {
    attempts_total: number;
    attempts_started: number;
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
    /** counted job page loads, today and the 29 days before */
    views_30d: number;
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
  events: { start: string | null; summary: string; location: string }[];
}

export type QueueItemKind = "job-quiz" | "integrity" | "unbooked" | "scorecard" | "scorecard-waiting";

/** A derived "Your queue" entry computed live by the backend (card D13). */
export interface QueueItem {
  key: string;
  kind: QueueItemKind;
  title: string;
  hint: string;
  href: string;
  since: string | null;
}

export const dashboard = {
  activity: (limit = 15) => request<ActivityItem[]>(`/api/v1/activity?limit=${limit}`),
  today: (tz: string) =>
    request<TodayPanelData>(`/api/v1/stats/today?tz=${encodeURIComponent(tz)}`),
  queue: {
    list: () => request<{ items: QueueItem[] }>("/api/v1/stats/queue"),
    dismiss: (key: string) =>
      request<void>("/api/v1/stats/queue/dismiss", {
        method: "POST",
        body: JSON.stringify({ key }),
      }),
  },
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
  display_name?: string | null;
  display_label?: string;
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
    /** Multi-mode signup marker, cleared by the inbox click (M5.7 H4). */
    pending_verification?: boolean;
    quiz_expired_reissue?: "manual" | "auto";
    legal_name?: string;
    privacy_contact_email?: string;
    retention_months?: number;
    privacy_policy_url?: string;
  };
  screening_questions: ScreeningQuestion[];
  scorecard_template?: ScorecardCriterion[];
}

/** Omit = untouched, null = reset to default (mirrors BrandingUpdate). */
export interface CompanySettingsUpdate {
  quiz_expired_reissue?: "manual" | "auto" | null;
  legal_name?: string | null;
  privacy_contact_email?: string | null;
  retention_months?: number | null;
  privacy_policy_url?: string | null;
  /** Replaces the company default set; omit to leave it untouched. */
  screening_questions?: ScreeningQuestion[] | null;
  /** Replaces the company default scorecard; omit to leave it untouched. */
  scorecard_template?: ScorecardCriterion[] | null;
}

export interface BrandingUpdate {
  /** Omit = untouched, null = reset to default. */
  primary_color?: string | null;
  radius?: "sharp" | "default" | "round" | null;
}

/** GET /company/usage: abuse-guard counters. A limit of 0 means off;
 * `warnings` lists counters at 80% or more, ready for the admin banner. */
export interface UsageOut {
  emails_today: number;
  emails_per_day_limit: number;
  applications_this_hour: number;
  applications_per_hour_limit: number;
  active_jobs: number;
  active_jobs_limit: number;
  warnings: string[];
}

/** Per-company API keys (card D4 part A): the secret exists only in the
 * create response; the list carries the prefix. */
export type ApiKeyScope = "read" | "write";

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scope: ApiKeyScope;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

/** Workspace email templates (card "Candidate emails", PR 3): one list call
 * gives every kind with its label, placeholders, the Ganek default's text
 * and the workspace's own templates. Writes are admin-only. */
export interface EmailTemplate {
  id: string;
  kind: EmailKind;
  name: string;
  subject: string;
  body: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmailKindInfo {
  kind: EmailKind;
  label: string;
  placeholders: string[];
  builtin: { subject: string; body: string };
  templates: EmailTemplate[];
}

export interface EmailTemplateInput {
  name: string;
  subject: string;
  body: string;
}

export const emailTemplates = {
  list: () => request<{ kinds: EmailKindInfo[] }>("/api/v1/company/email-templates"),
  create: (payload: EmailTemplateInput & { kind: EmailKind }) =>
    request<EmailTemplate>("/api/v1/company/email-templates", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: Partial<EmailTemplateInput>) =>
    request<EmailTemplate>(`/api/v1/company/email-templates/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  remove: (id: string) =>
    request<void>(`/api/v1/company/email-templates/${id}`, { method: "DELETE" }),
  setDefault: (id: string) =>
    request<EmailTemplate>(`/api/v1/company/email-templates/${id}/default`, { method: "POST" }),
  /** Back to the Ganek default for a kind: no custom template keeps the flag. */
  setBuiltinDefault: (kind: EmailKind) =>
    request<void>("/api/v1/company/email-templates/builtin/default", {
      method: "POST",
      body: JSON.stringify({ kind }),
    }),
  /** The editor's live preview: unsaved text rendered for a sample candidate. */
  preview: (payload: { kind: EmailKind; subject: string; body: string }) =>
    request<EmailPreview>("/api/v1/company/email-templates/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export const apiKeys = {
  list: () => request<ApiKey[]>("/api/v1/api-keys"),
  create: (payload: { name: string; scope: ApiKeyScope }) =>
    request<ApiKeyCreated>("/api/v1/api-keys", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revoke: (id: string) => request<void>(`/api/v1/api-keys/${id}`, { method: "DELETE" }),
};

/** Outbound webhooks (card D4 part B): endpoints with their last delivery;
 * the signing secret exists only in the create response. */
export type WebhookEvent = "application.created" | "stage.changed" | "quiz.completed";
export type DeliveryStatus = "queued" | "delivered" | "failed";

export interface WebhookDelivery {
  id: string;
  event: string;
  status: DeliveryStatus;
  attempts: number;
  last_error: string | null;
  response_status: number | null;
  created_at: string;
  delivered_at: string | null;
}

export interface WebhookEndpoint {
  id: string;
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
  created_at: string;
  last_delivery: WebhookDelivery | null;
}

export interface WebhookEndpointCreated extends WebhookEndpoint {
  secret: string;
}

export const webhooks = {
  list: () => request<WebhookEndpoint[]>("/api/v1/webhooks"),
  create: (payload: { name: string; url: string; events: WebhookEvent[] }) =>
    request<WebhookEndpointCreated>("/api/v1/webhooks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  remove: (id: string) => request<void>(`/api/v1/webhooks/${id}`, { method: "DELETE" }),
  test: (id: string) => request<WebhookDelivery>(`/api/v1/webhooks/${id}/test`, { method: "POST" }),
  deliveries: (id: string) => request<WebhookDelivery[]>(`/api/v1/webhooks/${id}/deliveries`),
};

/** Slug, name and instance mode for any role (GET /company/summary): what
 * the job overview needs to build public job URLs and share links. The
 * admin-only branding/settings view is `companyApi.get`. */
export interface CompanySummary {
  slug: string;
  name: string;
  mode: "single" | "multi";
  /** The default screening questions new jobs start with (every role reads it). */
  screening_questions: ScreeningQuestion[];
  /** The default scorecard criteria new jobs start with. */
  scorecard_template?: ScorecardCriterion[];
}

/** The public careers endpoints the SSR pages render from, reachable from
 * the admin too: the Google Jobs card builds the markup the public page
 * emits from these same payloads. Public jobs only: a draft or closed job
 * answers 404. */
export const publicPages = {
  company: (mode: "single" | "multi", slug: string) =>
    request<PublicCompanyPage>(
      mode === "multi" ? `/api/v1/public/companies/${slug}` : "/api/v1/public/company",
    ).then((page) => page.company),
  job: (mode: "single" | "multi", slug: string, jobSlug: string) =>
    request<PublicJobDetail>(
      mode === "multi"
        ? `/api/v1/public/companies/${slug}/jobs/${jobSlug}`
        : `/api/v1/public/company/jobs/${jobSlug}`,
    ),
};

export const companyApi = {
  get: () => request<CompanyAdmin>("/api/v1/company"),
  summary: () => request<CompanySummary>("/api/v1/company/summary"),
  usage: () => request<UsageOut>("/api/v1/company/usage"),
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

/** /api/health/deep: per-dependency status plus the arq worker's heartbeat
 * and last nightly purge (board card A2). Admin-only via the session cookie;
 * the request helper throws on 503, so callers treat a failure as "unknown". */
export interface DeepHealth {
  status: "ok" | "unhealthy";
  failing: string[];
  checks: Record<string, { ok: boolean; latency_ms: number; error?: string }>;
  smtp_configured: boolean;
  worker: { seen_at: string | null; last_purge_at: string | null };
  checked_at: string;
}

export const healthApi = {
  deep: () => request<DeepHealth>("/api/health/deep"),
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
