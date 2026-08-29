# Contributing to Ganek

Two ways to contribute: **code** and **questions**. Question contributions need zero backend knowledge.

## What's open vs. commercial (the litmus test)

Ganek is open core. The boundary is a published promise, not a vibe:

> Does a single company self-hosting Ganek need it to hire?
> → **AGPL core, forever.**
> Is it about running Ganek-as-a-service for many tenants (billing,
> quotas, tenant administration, custom-domain provisioning) or
> enterprise IT integration (SAML/SCIM)?
> → **`ee/`, commercial license.**

Two rules make this trustworthy:

- **No clawbacks.** Nothing shipped under AGPL ever moves to `ee/`.
- **Security is never paid.** Account-security basics land in core.

`ee/` ships empty today — the boundary is declared before any closed
code exists (see [ee/README.md](ee/README.md)).

## Contributing questions

Questions live in `questions/{domain}/{tag}.yaml` and are validated against `questions/schema.json`.

1. Pick a tag file (or start a new tag/domain pack — seeding rules in
   [questions/README.md](questions/README.md), "Starting a new tag or domain").
2. Add questions following the format in `questions/README.md`. Key rules:
   - Answerable in ~15 seconds by someone who knows the topic — recall/recognition, not puzzle-solving.
   - Exactly 4 options, exactly one clearly correct. No "all of the above", no trick ambiguity.
   - Distractors must be plausible (common misconceptions make the best wrong answers).
   - Difficulty is an integer 1–5 — the ladder is defined in `questions/README.md`; when unsure, rate down.
   - Include an `explanation` — shown to recruiters reviewing answers.
   - IDs are permanent slugs: `{tag-prefix}-{topic}-{n}` (e.g. `py-asyncio-gather-1`). Never reuse an ID.
3. Run `python questions/validate.py`.
4. Open a PR, updating the coverage table in `questions/README.md`. Reviewers check: technical correctness, unambiguity, difficulty rating, 15-second answerability.

To fix a wrong/leaked question: edit in place (same ID) for corrections; set `status: retired` for rotation. Never delete.

## Contributing code

### Setup

```bash
cd backend && uv sync
cd frontend && pnpm install
docker compose up postgres redis minio   # local services
pip install pre-commit && pre-commit install   # lint/format gate on every commit
```

### Conventions

- Backend: routers thin, business logic in `backend/app/services/`. Async everywhere. Pydantic schemas separate from SQLAlchemy models. Type hints mandatory (mypy strict is CI-blocking).
- Frontend: Next.js App Router; server components by default. Public careers pages must SSR.
- API: REST under `/api/v1`. Breaking changes to public endpoints need a deprecation note.
- Tests: service-layer functions get unit tests; quiz selection/scoring/deadline logic has the highest coverage bar in the repo. Bug fix = regression test first.
- Commits: [Conventional Commits](https://www.conventionalcommits.org) (`feat:`, `fix:`, `docs:`, `questions:`, `chore:`). Small, focused PRs from feature branches.

### Before pushing

Backend: `uv run pytest && uv run mypy app && uv run ruff check .`
Frontend: `pnpm typecheck && pnpm lint && pnpm test`
Question bank (if touched): `python questions/validate.py`

Browser e2e (`frontend/e2e/`, Playwright) covers the golden paths and runs in CI
against a fresh compose stack. If you touch the apply/quiz/review surfaces, run
it locally against a fresh scratch stack — `docker-compose.e2e.yml` swaps in
e2e-scoped data volumes so your dev data is never touched (commands in that
file's header). The suite registers the single-mode company itself and aborts
loudly if the stack already belongs to someone else.

### Non-negotiables (PRs violating these are rejected)

- `correct_key` must never appear in a public API schema.
- Quiz timing/scoring stays server-side; client timers are cosmetic.
- Tenant-scoped queries go through the tenancy dependency — never hand-written `WHERE company_id`.
- The quiz engine stays domain-agnostic: no domain-specific logic in code; new domains = new question packs.
- The tool never auto-rejects candidates. Scores and flags inform humans.
- No ML-based parsing, scoring, ranking, or adaptive testing. Deterministic scoring is a compliance boundary ([AI Act statement](docs/compliance/ai-act-statement.md)) — such a feature needs that analysis redone first, not just code review.
- No cookies, analytics, or third-party requests on candidate-facing pages (careers, apply, quiz, status, booking). There is deliberately nothing to consent-banner — adding any of these re-opens ePrivacy consent and the [telemetry legitimate-interests analysis](docs/compliance/telemetry-legitimate-interests.md).

## License and CLA

The core is AGPL-3.0. First-time contributors sign the
[Contributor License Agreement](CLA.md) — a bot asks on your first PR,
signing is one comment. You keep the copyright to your contribution;
the CLA grants Nestor Code Crafters UG a license broad enough that your
contribution can also ship in the hosted product and coexist with the
commercially licensed `ee/` code. What's AGPL stays AGPL — see the
no-clawbacks rule above.
