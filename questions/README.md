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
| asyncio | 5 | 9 | 4 | ❌ (18 total) |
| backend | 6 | 8 | 5 | ❌ (19 total) |
| devops | 6 | 7 | 4 | ❌ (17 total) |
| fastapi | 6 | 8 | 5 | ❌ (19 total) |
| frontend | 6 | 6 | 4 | ❌ (16 total) |
| git | 5 | 7 | 4 | ❌ (16 total) |
| go | 6 | 7 | 5 | ❌ (18 total) |
| javascript | 7 | 8 | 5 | ❌ (20 total) |
| python | 14 | 11 | 6 | ❌ (31 total) |
| react | 6 | 7 | 4 | ❌ (17 total) |
| sql | 6 | 8 | 4 | ❌ (18 total) |
| typescript | 5 | 7 | 4 | ❌ (16 total) |

(Update this table in PRs — total: 225 active questions. All 12 launch tags now have coverage; the ≥25-per-difficulty quiz-ready bar is the long-term target, grown via community PRs and further batches.)
