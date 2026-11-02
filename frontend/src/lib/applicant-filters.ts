import type {
  ApplicationFilters,
  ApplicationQuizState,
  ApplicationSortKey,
  ApplicationStage,
  ScreeningFilter,
} from "@/lib/api";

/** The applicant list's state lives in the URL (card "Applicant list"):
 * shareable, survives a refresh, works with the back button, and the
 * dashboard's deep links (`?job=`, `?selected=`) keep their meaning.
 * Defaults are omitted so the plain `/admin/applicants` link stays clean. */

export type SortKey = ApplicationSortKey;
export type QuizState = ApplicationQuizState;

export interface ApplicantFilters {
  /** Job id; "" = all jobs. */
  job: string;
  stage: ApplicationStage | "all";
  q: string;
  sort: SortKey;
  /** Minimum score in percent, 0..100. */
  score: number | null;
  quiz: QuizState | null;
  source: string | null;
  flagged: boolean | null;
  /** Applied within the last N days, 1..365. */
  days: number | null;
  /** Screening answers: all preferred matched, any mismatch, any skipped. */
  screening: ScreeningFilter | null;
  /** Live applications waiting on the team or on the candidate. */
  waiting: "team" | "candidate" | null;
}

export const DEFAULT_FILTERS: ApplicantFilters = {
  job: "",
  stage: "all",
  q: "",
  sort: "applied_desc",
  score: null,
  quiz: null,
  source: null,
  flagged: null,
  days: null,
  screening: null,
  waiting: null,
};

const STAGES: ReadonlySet<string> = new Set([
  "all",
  "new",
  "screening",
  "interview",
  "offer",
  "hired",
  "rejected",
  "withdrawn",
]);
const SORTS: ReadonlySet<string> = new Set([
  "applied_desc",
  "applied_asc",
  "score_desc",
  "score_asc",
  "name_asc",
  "stage_age_desc",
  "stage_age_asc",
]);
const SCREENING: ReadonlySet<string> = new Set(["match", "mismatch", "unanswered"]);
const QUIZ_STATES: ReadonlySet<string> = new Set([
  "none",
  "pending",
  "in_progress",
  "completed",
  "expired",
]);

function intInRange(raw: string | null, min: number, max: number): number | null {
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  return value >= min && value <= max ? value : null;
}

export function parseFilters(params: URLSearchParams): ApplicantFilters {
  const stage = params.get("stage");
  const sort = params.get("sort");
  const quiz = params.get("quiz");
  const flagged = params.get("flagged");
  const source = params.get("source");
  const screening = params.get("screening");
  const waiting = params.get("waiting");
  return {
    job: params.get("job") ?? "",
    stage: stage !== null && STAGES.has(stage) ? (stage as ApplicantFilters["stage"]) : "all",
    q: params.get("q") ?? "",
    sort: sort !== null && SORTS.has(sort) ? (sort as SortKey) : "applied_desc",
    score: intInRange(params.get("score"), 0, 100),
    quiz: quiz !== null && QUIZ_STATES.has(quiz) ? (quiz as QuizState) : null,
    source: source ? source : null,
    flagged: flagged === "true" ? true : flagged === "false" ? false : null,
    days: intInRange(params.get("days"), 1, 365),
    screening:
      screening !== null && SCREENING.has(screening) ? (screening as ScreeningFilter) : null,
    waiting: waiting === "team" || waiting === "candidate" ? waiting : null,
  };
}

export function filtersToParams(
  filters: ApplicantFilters,
  extra: Record<string, string> = {},
): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.job) params.set("job", filters.job);
  if (filters.stage !== "all") params.set("stage", filters.stage);
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.sort !== "applied_desc") params.set("sort", filters.sort);
  if (filters.score !== null) params.set("score", String(filters.score));
  if (filters.quiz !== null) params.set("quiz", filters.quiz);
  if (filters.source !== null) params.set("source", filters.source);
  if (filters.flagged !== null) params.set("flagged", String(filters.flagged));
  if (filters.days !== null) params.set("days", String(filters.days));
  if (filters.screening !== null) params.set("screening", filters.screening);
  if (filters.waiting !== null) params.set("waiting", filters.waiting);
  for (const [key, value] of Object.entries(extra)) {
    if (value) params.set(key, value);
  }
  return params;
}

export function toApiFilters(filters: ApplicantFilters): ApplicationFilters {
  const api: ApplicationFilters = {};
  if (filters.job) api.job_id = filters.job;
  if (filters.stage !== "all") api.stage = filters.stage;
  const q = filters.q.trim();
  if (q) api.q = q;
  if (filters.sort !== "applied_desc") api.sort = filters.sort;
  if (filters.score !== null) api.score_min = filters.score;
  if (filters.quiz !== null) api.quiz = filters.quiz;
  if (filters.source !== null) api.source = filters.source;
  if (filters.flagged !== null) api.flagged = filters.flagged;
  if (filters.days !== null) api.since_days = filters.days;
  if (filters.screening !== null) api.screening = filters.screening;
  if (filters.waiting !== null) api.waiting = filters.waiting;
  return api;
}

/** How many narrowing filters are on: search, score, quiz, source, flags,
 * date, screening, waiting. Job, stage and sort are navigation, not filters, so they do not
 * light up "Clear filters". */
export function countActive(filters: ApplicantFilters): number {
  return [
    filters.q.trim() !== "",
    filters.score !== null,
    filters.quiz !== null,
    filters.source !== null,
    filters.flagged !== null,
    filters.days !== null,
    filters.screening !== null,
    filters.waiting !== null,
  ].filter(Boolean).length;
}

/** The defaults for everything `countActive` counts; job, stage and sort stay. */
export function clearNarrowing(filters: ApplicantFilters): ApplicantFilters {
  return {
    ...filters,
    q: "",
    score: null,
    quiz: null,
    source: null,
    flagged: null,
    days: null,
    screening: null,
    waiting: null,
  };
}
