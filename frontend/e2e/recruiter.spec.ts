import { expect, test } from "@playwright/test";

import { ADMIN_EMAIL, ADMIN_PASSWORD, QUIZ_QUESTION_COUNT } from "./stack";

/** Golden path 2 — the recruiter: login UI → applicants review → open the
 * candidate that candidate.spec created earlier in this run → score +
 * answers + integrity visible → advance the stage → sign out. Runs after
 * candidate.spec (alphabetical, workers=1). */

const CANDIDATE_NAME = "Goldie Path";

test("recruiter logs in, reviews the applicant, and advances the stage", async ({ page }) => {
  await test.step("log in through the UI", async () => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(ADMIN_EMAIL);
    await page.getByLabel("Password").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page).toHaveURL(/\/admin/);
  });

  await test.step("open the applicant from the review list", async () => {
    await page.goto("/admin/applicants");
    const row = page.getByText(CANDIDATE_NAME).first();
    await expect(
      row,
      "no applicant from candidate.spec — this spec must run after it against the same stack",
    ).toBeVisible();
    await row.click();
  });

  await test.step("panel shows the completed quiz", async () => {
    await expect(page.getByText(`Q${QUIZ_QUESTION_COUNT}`, { exact: false }).first()).toBeVisible();
    await expect(page.getByText("Integrity").first()).toBeVisible();
  });

  await test.step("advance the stage", async () => {
    const stageSelect = page.getByLabel(new RegExp(`Stage for ${CANDIDATE_NAME}`)).first();
    await expect(stageSelect).toHaveValue("new");
    await page.getByRole("button", { name: "Advance", exact: true }).first().click();
    await expect(stageSelect).toHaveValue("screening");
  });

  await test.step("sign out lands on the login page", async () => {
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});
