import { type Page, expect, test } from "@playwright/test";

import { signInviteToken, stackSecretKey } from "./invite-token";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./stack";

/** Generic OIDC sign-in against a mock IdP (navikt/mock-oauth2-server).
 * Needs the stack started WITH docker-compose.oidc-e2e.yml and E2E_OIDC=1;
 * without them the whole file skips, so the default e2e run is unchanged.
 * Runs last (alphabetical, workers=1): it links an SSO identity to the
 * suite's admin, which the other specs never look at. */

const OIDC_ENABLED = process.env.E2E_OIDC === "1";
const IDP_ISSUER = process.env.E2E_OIDC_ISSUER ?? "http://localhost:8080/ganek";
const SSO_BUTTON = "Continue with Mock IdP";

test.describe("SSO (OIDC) sign-in", () => {
  test.skip(!OIDC_ENABLED, "set E2E_OIDC=1 and start the stack with docker-compose.oidc-e2e.yml");

  test.beforeAll(async ({ request }) => {
    // the JVM-based IdP can come up after the app; wait for its discovery doc
    for (let i = 0; i < 40; i += 1) {
      const probe = await request
        .get(`${IDP_ISSUER}/.well-known/openid-configuration`)
        .catch(() => null);
      if (probe?.ok()) return;
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
    throw new Error(`mock IdP not reachable at ${IDP_ISSUER}`);
  });

  /** The mock IdP's login page: any username becomes `sub`; the claims box
   * supplies the verified email the app links or matches on. */
  async function signInAtIdp(page: Page, subject: string, email: string): Promise<void> {
    await expect(page).toHaveURL(new RegExp(`^${IDP_ISSUER}/authorize`));
    await page.locator('input[name="username"]').fill(subject);
    await page
      .locator('textarea[name="claims"]')
      .fill(JSON.stringify({ email, email_verified: true }));
    await page.getByRole("button", { name: "Sign-in" }).click();
  }

  test("an existing account signs in with SSO and lands on /admin", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("link", { name: SSO_BUTTON }).click();
    // stable subject: the first run links it by verified email (domain is in
    // GANEK_OIDC_EMAIL_DOMAINS), reruns sign in by (issuer, sub)
    await signInAtIdp(page, "e2e-admin", ADMIN_EMAIL);
    await expect(page).toHaveURL(/\/admin(\/|$|\?)/);

    const me = await page.request.get("/api/v1/auth/me");
    expect(me.ok()).toBe(true);
    const body = (await me.json()) as { email: string; sso_linked: boolean };
    expect(body.email).toBe(ADMIN_EMAIL);
    expect(body.sso_linked).toBe(true);
  });

  test("an invite accepted through SSO creates the teammate", async ({ page, playwright }) => {
    const stamp = Date.now();
    const email = `sso-teammate-${stamp}@e2e.ganek.dev`;

    const baseURL = test.info().project.use.baseURL ?? "http://localhost:3000";
    const admin = await playwright.request.newContext({ baseURL });
    let inviteId: string;
    try {
      const login = await admin.post("/api/v1/auth/login", {
        data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
      });
      expect(login.ok(), "admin password login should succeed").toBe(true);
      const created = await admin.post("/api/v1/users/invites", {
        data: { email, role: "member" },
      });
      expect(created.status(), "invite creation should succeed").toBe(201);
      inviteId = ((await created.json()) as { id: string }).id;
    } finally {
      await admin.dispose();
    }

    const token = signInviteToken(inviteId, stackSecretKey());
    await page.goto(`/invite/${token}`);
    await expect(page.getByText(email).first()).toBeVisible();
    await page.getByRole("link", { name: SSO_BUTTON }).click();
    await signInAtIdp(page, `e2e-teammate-${stamp}`, email);
    await expect(page).toHaveURL(/\/admin(\/|$|\?)/);

    const me = await page.request.get("/api/v1/auth/me");
    expect(me.ok()).toBe(true);
    const body = (await me.json()) as {
      email: string;
      role: string;
      sso_linked: boolean;
      has_password: boolean;
    };
    expect(body.email).toBe(email);
    expect(body.role).toBe("member");
    expect(body.sso_linked).toBe(true);
    expect(body.has_password).toBe(false);
  });
});
