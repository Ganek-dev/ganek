import { defineConfig } from "@playwright/test";

/** Browser e2e for the golden paths. Assumes a RUNNING stack (fresh compose,
 * or one previously initialized by this suite) at E2E_BASE_URL — see the
 * `browser` job in .github/workflows/e2e.yml. Not part of `pnpm test`. */
export default defineConfig({
  testDir: "e2e",
  workers: 1, // specs share one live stack and build on each other's data
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  globalSetup: "./e2e/global-setup",
  reporter: process.env.CI ? [["html", { open: "never" }], ["line"]] : "line",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
});
