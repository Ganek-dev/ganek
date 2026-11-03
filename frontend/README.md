# Ganek frontend

Next.js (App Router, TypeScript, Tailwind). API calls are proxied same-origin
to the backend via `next.config.ts` rewrites (`BACKEND_URL`, default
`http://localhost:8000`), so session cookies just work.

Note: Next resolves rewrite destinations at **build** time. In dev,
`BACKEND_URL` is read when `pnpm dev` starts; in Docker it must be passed
as a build arg (compose already does: `http://backend:8000`).

```bash
pnpm install
pnpm dev          # http://localhost:3000 (backend must run on :8000)
pnpm lint && pnpm typecheck && pnpm test
pnpm build        # production build (standalone output for Docker)
```

Route map (see `src/app/`): `/c/[slug]` and `/jobs/[jobSlug]` are the public
careers pages (SSR, per-company theme); `/quiz/[token]`, `/application/[token]`
and `/interview/[token]` are the candidate surfaces; `/login`, `/setup`
(first-run company creation), `/reset`, `/verify` and `/invite/[token]` handle
accounts; `/admin/*` is the recruiter shell and `/review/*` the reviewer shell.

Notes:
- No `next/font/google` - build must not depend on Google's network (self-hosters build offline).
- shadcn/ui primitives live in `src/components/ui/` (dialog, menu, switch) and are adopted surface by surface; everything else stays hand-rolled on the design tokens in `globals.css`.
