---
title: Question packs
description: How the open question bank is organised, the authoring rules, and how to add a tag or a whole domain.
sidebar: { order: 1 }
---

The quiz engine is domain-agnostic. A domain is a directory of YAML files; a tag is one file. Nothing is registered in code, so a new field of work is purely a question pack. The bank ships with the software, is validated in CI and grows through community pull requests. Companies can also keep private questions of their own in the admin and block bank questions they dislike.

## Layout

```
questions/
  schema.json                  # validated by questions/validate.py
  software-engineering/
    python.yaml                # one file per primary tag
    asyncio.yaml
    sql.yaml
```

Each file declares `domain`, `tag` and a `questions` list:

```yaml
domain: software-engineering
tag: asyncio
questions:
  - id: py-asyncio-gather-1
    tags: [python]
    difficulty: 3
    prompt: "What does `asyncio.gather(a(), b())` do?"
    options:
      a: "Runs both coroutines concurrently and returns their results as a list"
      b: "Runs a() then b() sequentially"
      c: "Runs each coroutine in a separate OS thread"
      d: "Returns whichever coroutine finishes first and cancels the other"
    correct: a
    explanation: >
      gather schedules the awaitables concurrently on the event loop and
      resolves to a list of results in argument order.
```

Required per question: `id`, `difficulty`, `prompt`, `options`, `correct`, `explanation`. Optional: `tags`, `time_limit_seconds`, `locale`, `status`.

## Authoring rules

- **15-second rule.** Someone who knows the topic answers almost instantly; someone who does not cannot search it in time. Recall and recognition, not computation.
- Exactly four options, exactly one correct. Distractors are plausible misconceptions.
- No "all of the above" or "none of the above", no negatively worded tricks.
- Prompts and options take inline markdown (backticks for code).
- `explanation` is shown to recruiters reviewing answers, never to candidates.
- IDs are permanent: `{prefix}-{topic}-{n}`. Never reuse or renumber. Retire (`status: retired`) instead of deleting; to correct a wrong or leaked question, edit in place with the same id.

## Difficulty (1 to 5)

A label for the knowledge depth the question probes, not for how convoluted the prompt is. Every level still obeys the 15-second rule.

1. Anyone in the field answers instantly. Definitional, pure recognition.
2. Everyday working knowledge; comes up within weeks of normal work.
3. Solid practitioner. The workhorse band, most questions land here.
4. Experienced practitioner. Edge behaviour, internals, sharp corners.
5. Genuine expert. Rare by design; a level 5 that a strong mid-level person can answer is a 4.

When unsure, rate down. An inflated 4 wastes a recruiter's "hard" filter; an honest 3 keeps quiz composition predictable.

### Calibration from real answers

The question library shows, under each rating, how candidates in your workspace actually did: the share who answered correctly out of how many were served, with timeouts and the average response time in the tooltip. Only completed quizzes count; re-issued (invalidated) runs carry no evidence. Each rating has a band it usually lands in: 1 at 85% or more correct, 2 between 70% and 85%, 3 between 50% and 70%, 4 between 30% and 50%, 5 below 30%. With at least 20 answers, a correct rate more than 10 points outside the band shows a "looks easier" or "looks harder" chip.

The chip is a prompt for a human, not a verdict: a question nobody misses may be well known in your niche rather than mis-rated. Nothing changes automatically, and neither scoring nor quiz selection reads these numbers. Ratings change the way everything in the bank changes, through a `questions:` pull request with the evidence in the description.

## A new tag or domain

- New tag: add `{domain}/{tag}.yaml` with a fresh permanent prefix. Seed about fifteen active questions spread over levels 1 to 4 before announcing it; below that, tag-matched quizzes repeat questions too often. Jobs can attach a curated questionnaire meanwhile.
- New domain: a new directory. Nothing to register.
- Update the coverage table in [questions/README.md](https://github.com/Ganek-dev/ganek/blob/main/questions/README.md) in the same pull request.

## Contributing

1. Not sure the pack fits? Open a [question pack proposal](https://github.com/Ganek-dev/ganek/issues/new/choose) with the domain, the tag and three sample questions.
2. Write the YAML and run `python questions/validate.py`.
3. Open a pull request. Reviewers check technical correctness, unambiguity, the difficulty rating and 15-second answerability. First-time contributors sign the CLA with one comment on the pull request.

The live coverage table and the long-term bar (25 active questions per level 1 to 4 per tag) live in the repository README for the bank.
