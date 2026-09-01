# Ganek Question Bank

Open, community-maintained pool of screening questions. Layout: `{domain}/{tag}.yaml`, one file per primary tag. Validated by `schema.json` - run `python questions/validate.py` before committing.

## Authoring rules

- **15-second rule:** someone who knows the topic answers almost instantly; someone who doesn't can't Google it in time. Recall and recognition, not computation.
- Exactly one correct option; distractors = plausible misconceptions.
- No "all/none of the above", no negatively-worded trick questions.
- Prompts and options support inline markdown (backticks for code).
- IDs are permanent: `{prefix}-{topic}-{n}`. Never reuse or renumber. Retire (`status: retired`) instead of deleting.

## Difficulty (integer 1-5)

Label for the *knowledge depth* the question probes, not how convoluted the
prompt is - every level still obeys the 15-second rule:

1. Anyone in the field answers instantly - definitional, pure recognition.
2. Everyday working knowledge - comes up in normal work within weeks.
3. Solid practitioner - the workhorse band; most questions land here.
4. Experienced practitioner - edge behavior, internals, sharp corners.
5. Genuine expert - use sparingly; a level 5 that a strong mid-level person
   can answer is a 4. The bank keeps 5 deliberately rare (one exists today).

When unsure, rate down: an inflated 4 wastes a recruiter's "hard" filter,
while an honest 3 keeps quiz composition predictable.

## Starting a new tag or domain

- New tag: add `{domain}/{tag}.yaml` with a fresh permanent prefix. Seed at
  least ~15 active questions spread over levels 1-4 before announcing it -
  below that, tag-auto quizzes repeat questions too often (jobs can attach a
  curated questionnaire meanwhile).
- New domain: just a new directory - the engine is domain-agnostic; nothing
  to register in code.
- Update the coverage table below in the same PR.

## Coverage

Active questions per difficulty level:

| Tag | 1 | 2 | 3 | 4 | 5 | Total |
|---|---|---|---|---|---|---|
| asyncio | 3 | 2 | 9 | 4 | 0 | 18 |
| backend | 3 | 3 | 8 | 5 | 0 | 19 |
| devops | 3 | 3 | 7 | 4 | 0 | 17 |
| fastapi | 3 | 3 | 8 | 5 | 0 | 19 |
| frontend | 2 | 4 | 6 | 4 | 0 | 16 |
| git | 2 | 3 | 7 | 4 | 0 | 16 |
| go | 4 | 2 | 7 | 5 | 0 | 18 |
| javascript | 3 | 4 | 8 | 5 | 0 | 20 |
| python | 5 | 9 | 11 | 5 | 1 | 31 |
| react | 4 | 2 | 7 | 4 | 0 | 17 |
| sql | 3 | 3 | 8 | 4 | 0 | 18 |
| typescript | 3 | 2 | 7 | 4 | 0 | 16 |

(Update this table in PRs - total: 225 active questions. Long-term
quiz-ready bar: ≥25 active questions in each of levels 1-4 per tag; level 5
stays rare by design and sits outside the bar. Grown via community PRs.)
