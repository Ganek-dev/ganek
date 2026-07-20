# Vetd frontend

Not scaffolded yet — done in milestone M0 to avoid a stale hand-written skeleton.

Bootstrap with:

```bash
pnpm create next-app@latest . --typescript --tailwind --eslint --app --src-dir --use-pnpm
pnpm dlx shadcn@latest init
```

Then structure routes as described in `docs/ARCHITECTURE.md`:

- `src/app/(public)/` — careers pages, application form, quiz flow (SSR, SEO-critical)
- `src/app/(admin)/` — dashboard, jobs, applicants, settings (auth-gated)

Add scripts to package.json: `typecheck` (tsc --noEmit), `test` (vitest), `e2e` (playwright test).
