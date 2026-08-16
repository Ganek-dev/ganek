import { type APIRequestContext, expect } from "@playwright/test";

/** Identity the suite owns on the stack under test. Register-or-login makes
 * reruns against the same stack work; anything else fails loudly so a
 * misconfigured stack never surfaces as spec flake. */
export const ADMIN_EMAIL = "admin@e2e.vetd.dev";
export const ADMIN_PASSWORD = "e2e-super-secret-password";
export const COMPANY_NAME = "E2E Test Co";
export const QUIZ_JOB_TITLE = "E2E Quiz Engineer";
export const QUIZ_JOB_SLUG = "e2e-quiz-engineer";
export const QUIZ_QUESTION_COUNT = 3;

export async function ensureCompanyAndJob(api: APIRequestContext): Promise<void> {
  const register = await api.post("/api/v1/auth/register", {
    data: { company_name: COMPANY_NAME, email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  if (register.status() === 409) {
    // single mode already has a company — it must be ours (fresh-stack suite)
    const login = await api.post("/api/v1/auth/login", {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(
      login.ok(),
      "stack already has a company that is not the e2e one — run against a fresh stack",
    ).toBe(true);
  } else {
    expect(register.status(), "first-run registration should succeed").toBe(201);
  }

  const jobs = await api.get("/api/v1/jobs");
  expect(jobs.ok()).toBe(true);
  const list = (await jobs.json()) as { title: string }[];
  if (list.some((job) => job.title === QUIZ_JOB_TITLE)) return;

  const created = await api.post("/api/v1/jobs", {
    data: {
      title: QUIZ_JOB_TITLE,
      location: "Remote",
      remote_policy: "remote",
      tags: ["python"],
      description_md: "End-to-end golden path role. You will **click** things.",
      quiz_config: {
        enabled: true,
        tags: ["python"],
        question_count: QUIZ_QUESTION_COUNT,
        time_limit_seconds: 20,
      },
    },
  });
  expect(created.status(), "job creation should succeed").toBe(201);
  const { id } = (await created.json()) as { id: string };
  const published = await api.post(`/api/v1/jobs/${id}/publish`);
  expect(published.ok(), "job publish should succeed").toBe(true);
}
