# Contributing to Vetd

Two ways to contribute: **code** and **questions**. Question contributions need zero backend knowledge.

## Contributing questions

Questions live in `questions/{domain}/{tag}.yaml` and are validated against `questions/schema.json`.

1. Pick a tag file (or create one: `questions/software-engineering/rust.yaml`).
2. Add questions following the format in `questions/README.md`. Key rules:
   - Answerable in ~15 seconds by someone who knows the topic — recall/recognition, not puzzle-solving.
   - Exactly 4 options, exactly one clearly correct. No "all of the above", no trick ambiguity.
   - Distractors must be plausible (common misconceptions make the best wrong answers).
   - Include an `explanation` — shown to recruiters reviewing answers.
   - IDs are permanent slugs: `{tag-prefix}-{topic}-{n}` (e.g. `py-asyncio-gather-1`). Never reuse an ID.
3. Run `python questions/validate.py`.
4. Open a PR. Reviewers check: technical correctness, unambiguity, difficulty label, 15-second answerability.

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

### Non-negotiables (PRs violating these are rejected)

- `correct_key` must never appear in a public API schema.
- Quiz timing/scoring stays server-side; client timers are cosmetic.
- Tenant-scoped queries go through the tenancy dependency — never hand-written `WHERE company_id`.
- The quiz engine stays domain-agnostic: no domain-specific logic in code; new domains = new question packs.
- The tool never auto-rejects candidates. Scores and flags inform humans.
- No ML-based parsing, scoring, ranking, or adaptive testing. Deterministic scoring is a compliance boundary ([AI Act statement](docs/compliance/ai-act-statement.md)) — such a feature needs that analysis redone first, not just code review.

## License

Contributions are licensed under AGPL-3.0. By submitting a PR you agree to license your contribution under the project license.
