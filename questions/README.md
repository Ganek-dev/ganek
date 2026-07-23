# Vetd Question Bank

Open, community-maintained pool of screening questions. Layout: `{domain}/{tag}.yaml`, one file per primary tag. Validated by `schema.json` — run `python questions/validate.py` before committing.

## Authoring rules

- **15-second rule:** someone who knows the topic answers almost instantly; someone who doesn't can't Google it in time. Recall and recognition, not computation.
- Exactly one correct option; distractors = plausible misconceptions.
- No "all/none of the above", no negatively-worded trick questions.
- Prompts and options support inline markdown (backticks for code).
- IDs are permanent: `{prefix}-{topic}-{n}`. Never reuse or renumber. Retire (`status: retired`) instead of deleting.
- A tag is **quiz-ready** at ≥25 active questions per difficulty level.

## Coverage

| Tag | easy | medium | hard | Quiz-ready |
|---|---|---|---|---|
| python | 14 | 11 | 6 | ❌ (growing — batch 1 landed) |
| asyncio | 1 | 2 | 0 | ❌ (seed examples only) |

(Update this table in PRs. Target for launch: python, asyncio, fastapi, javascript, typescript, react, go, sql, backend, frontend, devops, git.)
