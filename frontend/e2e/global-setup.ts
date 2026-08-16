import { request, type FullConfig } from "@playwright/test";

import { ensureCompanyAndJob } from "./stack";

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use?.baseURL ?? "http://localhost:3000";
  const api = await request.newContext({ baseURL });
  try {
    await ensureCompanyAndJob(api);
  } finally {
    await api.dispose();
  }
}
