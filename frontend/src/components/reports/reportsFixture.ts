import type { ReportsOut } from "@/lib/api";

/** One ReportsOut as the API returns it (the R3 07 numbers); tests spread it
 * and override what they need. */
export const reportsFixture: ReportsOut = {
  period: "90d",
  job_id: null,
  cohort: {
    applications: 142,
    reached_interview: 31,
    hires: 3,
    median_time_to_hire_days: 24,
    hires_n: 3,
  },
  previous: {
    applications: 124,
    reached_interview: 35,
    hires: 2,
    median_time_to_hire_days: null,
    hires_n: 2,
  },
  funnel: [
    { stage: "new", reached: 142, pass_through: 62, rejected_from: 38, withdrawn_from: 6, still_here: 10 },
    { stage: "screening", reached: 88, pass_through: 35.2, rejected_from: 42, withdrawn_from: 5, still_here: 10 },
    { stage: "interview", reached: 31, pass_through: 19.4, rejected_from: 16, withdrawn_from: 3, still_here: 6 },
    { stage: "offer", reached: 6, pass_through: 50, rejected_from: 0, withdrawn_from: 1, still_here: 2 },
    { stage: "hired", reached: 3, pass_through: null, rejected_from: 0, withdrawn_from: 0, still_here: 0 },
  ],
  quiz: { invited: 120, completed: 97, expired: 14 },
  time_in_stage: [
    { stage: "new", median_days: 3, n: 132, oldest_live_days: 6 },
    { stage: "screening", median_days: 9, n: 78, oldest_live_days: 18 },
    { stage: "interview", median_days: 6, n: 25, oldest_live_days: 11 },
    { stage: "offer", median_days: 4, n: 4, oldest_live_days: 4 },
  ],
  sources: [
    { source: "linkedin", applications: 41, reached_interview: 8, hires: 1 },
    { source: "direct", applications: 58, reached_interview: 14, hires: 2 },
    { source: "indeed", applications: 23, reached_interview: 4, hires: 0 },
  ],
  diagnosis: [
    "Most candidates leave between Screening and Interview: 35 percent move on.",
    "Candidates wait longest in Screening: median 9 days (n = 78).",
  ],
  quiz_scores: {
    attempts_total: 120,
    attempts_started: 120,
    attempts_completed: 97,
    completion_rate: 0.81,
    avg_score: 0.64,
    median_score: 0.66,
    avg_duration_seconds: 900,
    score_distribution: [1, 2, 4, 7, 11, 15, 21, 19, 12, 5],
  },
  weekly: [
    { week_start: "2026-10-05", count: 9 },
    { week_start: "2026-10-12", count: 14 },
    { week_start: "2026-10-19", count: 11 },
  ],
};
