import path from "node:path";

import { expect, test } from "@playwright/test";

import { COMPANY_NAME, QUIZ_JOB_SLUG, QUIZ_JOB_TITLE, QUIZ_QUESTION_COUNT } from "./stack";

/** Golden path 1 — the candidate: careers page → job detail → apply with a
 * CV → assessment invite → rules gate → answer every question → finished
 * screen → status page. Runs first (alphabetical, workers=1); the recruiter
 * spec reviews the applicant this test creates. */

const CANDIDATE_NAME = "Goldie Path";
// unique per run/retry so a CI retry re-applies instead of hitting the 409 dup guard
const candidateEmail = `e2e-candidate-${Date.now()}@e2e.ganek.dev`;

test("candidate applies, takes the quiz, and lands on the status page", async ({ page }) => {
  await test.step("careers page lists the job (SSR, single mode)", async () => {
    await page.goto("/");
    await expect(page.getByText(COMPANY_NAME).first()).toBeVisible();
    await page.getByRole("link", { name: new RegExp(QUIZ_JOB_TITLE) }).first().click();
    await expect(page).toHaveURL(new RegExp(`/jobs/${QUIZ_JOB_SLUG}`));
    await expect(page.getByRole("heading", { name: QUIZ_JOB_TITLE }).first()).toBeVisible();
  });

  await test.step("apply with a CV upload", async () => {
    await expect(
      page.getByText(/processes your details to consider/),
      "the Art. 13 notice line must sit on the form",
    ).toBeVisible();
    await page.getByLabel("Name").fill(CANDIDATE_NAME);
    await page.getByLabel("Email").fill(candidateEmail);
    await page
      .getByLabel("CV (PDF)")
      .setInputFiles(path.join(__dirname, "fixtures", "cv.pdf"));
    await expect(page.getByText(/uploaded · /)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Submit application" }).click();
  });

  await test.step("confirmation offers the assessment", async () => {
    await expect(page.getByText(/Application received, Goldie/)).toBeVisible();
    await page.getByRole("link", { name: "Start assessment now" }).click();
  });

  await test.step("rules gate discloses monitoring and the skip option", async () => {
    await expect(page.getByText(/Ready when you are, Goldie/)).toBeVisible();
    await expect(
      page.getByText(/tab switches \(and how long\), pastes, and window resizes/),
    ).toBeVisible();
    await expect(page.getByText(/application still stands/)).toBeVisible();
    // the start button stays disabled until monitoring is acknowledged
    await expect(page.getByRole("button", { name: "Start the real assessment" })).toBeDisabled();
    await page.getByRole("checkbox", { name: /integrity monitoring/ }).check();
    await page.getByRole("button", { name: "Start the real assessment" }).click();
  });

  await test.step("answer every question", async () => {
    for (let i = 1; i <= QUIZ_QUESTION_COUNT; i++) {
      await expect(page.getByText(`Question ${i}`, { exact: false })).toBeVisible();
      // the four option cards are the only aria-pressed buttons on screen
      await page.locator("button[aria-pressed]").first().click();
      await page
        .getByRole("button", { name: /Lock answer/ })
        .filter({ visible: true })
        .click();
    }
    await expect(page.getByText(/That's it — submitted/)).toBeVisible();
  });

  await test.step("status page shows the timeline and the data block", async () => {
    await page.getByRole("link", { name: /track your application/i }).click();
    await expect(page.getByText("Assessment completed")).toBeVisible();
    await expect(page.getByText("Under review")).toBeVisible();
    await expect(page.getByText("Your data", { exact: true })).toBeVisible();
  });
});
