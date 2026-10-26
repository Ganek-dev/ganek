import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  DRAFT_JOB_TITLE,
  QUIZ_JOB_SLUG,
  QUIZ_JOB_TITLE,
  QUIZ_QUESTION_COUNT,
} from "./stack";

/** Golden path 2 — the recruiter: login UI → applicants review → open the
 * candidate that candidate.spec created earlier in this run → score +
 * answers + integrity visible → advance the stage → sign out. Runs after
 * candidate.spec (alphabetical, workers=1). */

const CANDIDATE_NAME = "Goldie Path";

test("recruiter logs in, reviews the applicant, and advances the stage", async ({
  page,
  context,
  browser,
}) => {
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

  await test.step("panel shows the completed quiz and where the candidate came from", async () => {
    await expect(page.getByText(`Q${QUIZ_QUESTION_COUNT}`, { exact: false }).first()).toBeVisible();
    await expect(page.getByText("Integrity").first()).toBeVisible();
    await expect(page.getByText(/via link:e2e-link/)).toBeVisible();
  });

  await test.step("advance the stage", async () => {
    const stageSelect = page.getByLabel(new RegExp(`Stage for ${CANDIDATE_NAME}`)).first();
    await expect(stageSelect).toHaveValue("new");
    await page.getByRole("button", { name: "Advance", exact: true }).first().click();
    await expect(stageSelect).toHaveValue("screening");
  });

  await test.step("job row opens the overview, Edit opens the form, save returns", async () => {
    await page.goto("/admin/jobs");
    await page.getByRole("link", { name: QUIZ_JOB_TITLE }).click();
    await expect(page).toHaveURL(/\/admin\/jobs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: QUIZ_JOB_TITLE })).toBeVisible();
    await expect(page.getByText("Pipeline")).toBeVisible();
    await expect(page.getByRole("link", { name: CANDIDATE_NAME })).toBeVisible();
    await page.getByRole("link", { name: "Edit" }).click();
    await expect(page).toHaveURL(/\/admin\/jobs\/[0-9a-f-]{36}\/edit$/);
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page).toHaveURL(/\/admin\/jobs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: QUIZ_JOB_TITLE })).toBeVisible();
  });

  await test.step("the candidate's visit was counted, the recruiter's is not", async () => {
    const viewsValue = page.locator("div.card", { hasText: "Views · 30d" }).first().locator("p").nth(1);
    await expect(viewsValue).toHaveText(/^[\d,]+$/);
    const before = Number((await viewsValue.textContent())!.replace(/,/g, ""));
    expect(before, "candidate.spec loaded the job page once as a person").toBeGreaterThanOrEqual(1);
    const sourceRow = page
      .locator("div.card", { hasText: "Sources" })
      .first()
      .getByRole("row", { name: /link:e2e-link/ });
    await expect(sourceRow).toBeVisible();
    const rowViews = Number((await sourceRow.getByRole("cell").nth(1).textContent())!.replace(/,/g, ""));
    expect(rowViews).toBeGreaterThanOrEqual(1);

    // the signed-in recruiter opens the live page on this domain: not a view
    const overviewUrl = page.url();
    await page.goto(`/jobs/${QUIZ_JOB_SLUG}`);
    await expect(page.getByRole("heading", { name: QUIZ_JOB_TITLE }).first()).toBeVisible();
    await page.goto(overviewUrl);
    await expect(
      page.locator("div.card", { hasText: "Views · 30d" }).first().locator("p").nth(1),
    ).toHaveText(before.toLocaleString("en-US"));
  });

  await test.step("a tracked share link lands in the sources table under its name", async () => {
    const shareCard = page.locator("div.card", { hasText: "Share this job" }).first();
    const linkedinRow = shareCard.getByRole("listitem").filter({ hasText: "LinkedIn" });
    const shown = (await linkedinRow.locator("span").nth(1).textContent())!.trim();
    expect(shown).toMatch(/\?src=linkedin$/);
    // a stranger opens it: fresh context, no recruiter cookie, same desktop UA
    const visitor = await browser.newContext({ baseURL: page.url() });
    const visitorPage = await visitor.newPage();
    await visitorPage.goto(`${new URL(page.url()).protocol}//${shown}`);
    await expect(visitorPage.getByRole("heading", { name: QUIZ_JOB_TITLE }).first()).toBeVisible();
    await visitor.close();
    await page.reload();
    const sourcesRow = page
      .locator("div.card", { hasText: "Sources" })
      .first()
      .getByRole("row", { name: /^linkedin\b/ });
    await expect(sourcesRow).toBeVisible();
    const rowViews = Number((await sourcesRow.getByRole("cell").nth(1).textContent())!.replace(/,/g, ""));
    expect(rowViews).toBeGreaterThanOrEqual(1);
  });

  await test.step("a draft previews as the candidate sees it, without applying", async () => {
    await page.goto("/admin/jobs?status=draft");
    await page.getByRole("link", { name: DRAFT_JOB_TITLE }).click();
    await expect(page.getByRole("heading", { name: DRAFT_JOB_TITLE })).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy preview link" })).toBeVisible();
    const [preview] = await Promise.all([
      context.waitForEvent("page"),
      page.getByRole("button", { name: "View as candidate", exact: true }).click(),
    ]);
    await expect(preview).toHaveURL(/\/jobs\/[a-z0-9-]+\?preview=/);
    await expect(preview.getByRole("status")).toContainText("Preview, not live.");
    await expect(preview.getByText("Applications open when the job is published.")).toBeVisible();
    await expect(preview.locator('script[type="application/ld+json"]')).toHaveCount(0);
    await expect(preview.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
    await expect(preview.getByRole("button", { name: /Apply/ })).toHaveCount(0);
    await preview.close();
  });

  await test.step("sign out lands on the login page", async () => {
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});
